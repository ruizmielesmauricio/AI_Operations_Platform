"""Orchestrates the ingestion pipeline's upload and detection steps (PR-2,
ADR-008). Route handlers stay thin (CLAUDE.md) — this is where that logic
lives, one level above the R2 SDK boundary in app/imports/r2_client.py.
"""

import os
import uuid
from dataclasses import dataclass, field as dataclass_field

from sqlalchemy.orm import Session

from app.imports import detection, file_parser, r2_client
from app.imports.aliases import CANONICAL_FIELDS, MINIMUM_MAPPING_RULES, SUPPORTED_ENTITY_TYPES
from app.imports.detection import FieldCandidate, Row
from app.imports.exceptions import (
    FileTooLarge,
    HeaderRowNotFound,
    InsufficientMapping,
    InvalidFieldMapping,
    UnsupportedEntityType,
    UnsupportedFileType,
    UploadNotReady,
)
from app.imports.file_parser import normalize_cell
from app.models.import_record import ImportRecord
from app.models.upload import Upload
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository

# PR-2.1's accepted extensions. Checked against the filename, not the
# client-supplied content type, which browsers are inconsistent about for
# spreadsheet files and which is trivial to spoof anyway.
_ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}

# One bounded read covers both the header-search window (detection.py looks
# at the first 15 rows) and the structural-sampling window (200 rows after
# the header) — detection cost stays ~constant regardless of file size.
_DETECTION_WINDOW_ROWS = 215

# This step runs synchronously inside a request handler (no background job
# queue exists yet), so a many-tens-of-MB file is a real risk, not just the
# parsing logic itself.
_MAX_DETECTION_FILE_SIZE_BYTES = 20 * 1024 * 1024

# Deliberately wider than detection.py's own 15-row auto-search window —
# the manual picker exists specifically to rescue files auto-detection
# couldn't handle, including a header further down than auto-detection
# ever looked, not just an ambiguous one within that same window. Free to
# widen: these rows are already read as part of the same bounded window
# (_DETECTION_WINDOW_ROWS), this only changes how many get echoed back.
_HEADER_PREVIEW_ROWS = 40


def create_upload(
    db: Session, *, business_id: uuid.UUID, filename: str, uploaded_by: str, entity_type: str
) -> tuple[Upload, str]:
    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise UnsupportedEntityType(entity_type)

    _, extension = os.path.splitext(filename.lower())
    if extension not in _ALLOWED_EXTENSIONS:
        raise UnsupportedFileType(extension)

    storage_key = f"{business_id}/{uuid.uuid4()}{extension}"
    # Presign before persisting: if R2 rejects this (bad bucket, credential
    # issue), there must be no orphaned "pending" row left behind with no
    # upload_url ever handed out and no way to retry it.
    upload_url = r2_client.generate_upload_url(storage_key=storage_key)
    upload = UploadRepository(db).create(
        business_id=business_id,
        storage_key=storage_key,
        original_filename=filename,
        uploaded_by=uploaded_by,
        entity_type=entity_type,
    )
    return upload, upload_url


def mark_uploaded(db: Session, upload: Upload) -> Upload:
    return UploadRepository(db).set_status(upload, status="uploaded")


@dataclass
class ConfirmMappingResult:
    status: str  # "confirmed" | "needs_location_confirmation"
    import_record: ImportRecord | None
    mapping_profile_id: uuid.UUID | None
    # Only populated when status == "needs_location_confirmation": the
    # distinct values found in the mapped "location" column (BD-007
    # anti-bypass check — see _distinct_location_values below). More than
    # one means this file looks like it combines more than one physical
    # location's data into a single business, which is exactly the
    # branch-fee bypass this check exists to catch.
    locations: list[str] | None = None


@dataclass
class DetectMappingResult:
    status: str  # "reused" | "needs_confirmation" | "header_not_found"
    mapping_profile_id: uuid.UUID | None
    suggested_mapping: dict[str, str | None]
    columns: list[str] = dataclass_field(default_factory=list)
    field_candidates: dict[str, list[FieldCandidate]] = dataclass_field(default_factory=dict)
    unmapped_columns: list[str] = dataclass_field(default_factory=list)
    # Only populated when status == "header_not_found" — the first ~15 raw
    # rows, for the frontend to render as a "click the header row" picker
    # (PR-2.2's escape hatch when auto-detection can't find it confidently).
    preview_rows: list[list[str]] | None = None


def download_checked(storage_key: str) -> bytes:
    """Shared with app/imports/importer.py — same 20MB guard for both
    detection (bounded read) and the full import (needs every row)."""
    size = r2_client.get_object_size(storage_key=storage_key)
    if size > _MAX_DETECTION_FILE_SIZE_BYTES:
        raise FileTooLarge(size, _MAX_DETECTION_FILE_SIZE_BYTES)
    return r2_client.download_object(storage_key=storage_key)


def _read_grid(upload: Upload) -> list[Row]:
    file_bytes = download_checked(upload.storage_key)
    return file_parser.read_rows(file_bytes, upload.original_filename, max_rows=_DETECTION_WINDOW_ROWS)


def _detect(upload: Upload, grid: list[Row], header_row_index: int | None) -> detection.DetectionResult:
    if header_row_index is not None:
        return detection.detect_mapping_with_header(grid, upload.entity_type, header_row_index)
    return detection.detect_mapping(grid, upload.entity_type)


def _preview_rows(grid: list[Row]) -> list[list[str]]:
    return [[normalize_cell(c) for c in row] for row in grid[:_HEADER_PREVIEW_ROWS]]


def detect_mapping_for_upload(
    db: Session, upload: Upload, header_row_index: int | None = None
) -> DetectMappingResult:
    # "mapped" is a remap attempt (a confirmed-but-not-yet-run upload getting
    # its mapping fixed) — first-time mapping only ever starts from
    # "uploaded". Remapping an upload whose import already ran (status
    # "imported", whether reversed or not) stays unsupported: the source
    # file is deleted from R2 right after a successful import (ADR-008),
    # so there's nothing left here to re-read — that case's recovery path
    # is re-uploading the file, unchanged.
    if upload.status not in ("uploaded", "mapped"):
        raise UploadNotReady(upload.status)
    is_remap = upload.status == "mapped"

    grid = _read_grid(upload)
    try:
        result = _detect(upload, grid, header_row_index)
    except HeaderRowNotFound:
        # Only reachable when header_row_index was None — the manual path
        # raises InvalidHeaderRowIndex instead, which is a genuine client
        # bug (stale preview_rows), not something to fall back from.
        return DetectMappingResult(
            status="header_not_found",
            mapping_profile_id=None,
            suggested_mapping={},
            preview_rows=_preview_rows(grid),
        )
    columns = [c for c in result.columns if c]

    # Skipped on remap: confirm_mapping's own upsert() already saved the
    # user's just-rejected mapping as this exact source's profile, so the
    # normal reuse check would find it and silently reapply the same
    # mistake via the "reused" fast path, before the user ever sees the
    # form again — defeating the point of remapping.
    if not is_remap:
        existing = ImportMappingProfileRepository(db).get_by_signature(
            upload.business_id, result.source_signature
        )
        if existing is not None:
            # The saved mapping is what gets used going forward, not a fresh
            # (possibly different) heuristic guess — reuse means zero input,
            # not "here's another suggestion" (PR-2.5). That promise means the
            # upload is actually finished here, not left at "uploaded" waiting
            # for a confirmation step that will never come.
            ImportRecordRepository(db).create(
                business_id=upload.business_id,
                upload_id=upload.id,
                mapping_profile_id=existing.id,
                entity_type=upload.entity_type,
                status="mapped",
            )
            UploadRepository(db).set_status(upload, status="mapped")
            return DetectMappingResult(
                status="reused",
                mapping_profile_id=existing.id,
                suggested_mapping=existing.column_mapping["fields"],
                columns=columns,
            )
    return DetectMappingResult(
        status="needs_confirmation",
        mapping_profile_id=None,
        suggested_mapping=result.suggested_mapping,
        columns=columns,
        field_candidates=result.field_candidates,
        unmapped_columns=result.unmapped_columns,
    )


def _distinct_location_values(
    grid: list[Row], result: detection.DetectionResult, location_column: str
) -> list[str]:
    """Scans the same bounded detection-window grid already read for this
    request (no second file read) for every distinct non-blank value in
    the mapped location column — the BD-007 anti-bypass signal. Honest
    limitation, accepted: data split across more than _DETECTION_WINDOW_ROWS
    rows won't all be seen, same bounded-window trade-off detection.py
    already makes everywhere else.
    """
    column_index = result.columns.index(location_column)
    values: dict[str, None] = {}  # dict, not set — preserves first-seen order
    for row in grid[result.header_row_index + 1 :]:
        if column_index >= len(row):
            continue
        value = normalize_cell(row[column_index])
        if value:
            values.setdefault(value, None)
    return list(values.keys())


def confirm_mapping(
    db: Session,
    upload: Upload,
    field_mapping: dict[str, str | None],
    header_row_index: int | None = None,
    confirm_multiple_locations: bool = False,
) -> ConfirmMappingResult:
    # See detect_mapping_for_upload's docstring note — same relaxed
    # precondition, same "imported" scope boundary.
    if upload.status not in ("uploaded", "mapped"):
        raise UploadNotReady(upload.status)

    # Re-run detection rather than trust the client's payload shape/columns
    # past the membership check — a stale frontend or tampered request must
    # fail loudly, not silently under-map or reference a column that isn't
    # actually in this file. header_row_index is threaded through from
    # detect-mapping's manual-pick path (PR-2.2's escape hatch) — omitted
    # entirely for the normal auto-detected case.
    grid = _read_grid(upload)
    result = _detect(upload, grid, header_row_index)
    canonical_fields = set(CANONICAL_FIELDS[upload.entity_type])
    if set(field_mapping.keys()) != canonical_fields:
        raise InvalidFieldMapping("field_mapping must include exactly the canonical fields for this entity type")
    valid_columns = set(result.columns)
    for column in field_mapping.values():
        if column is not None and column not in valid_columns:
            raise InvalidFieldMapping(f"'{column}' is not a column in this file")

    if not MINIMUM_MAPPING_RULES[upload.entity_type](field_mapping):
        raise InsufficientMapping(upload.entity_type)

    # BD-007 anti-bypass check — a real direct request: block a file that
    # itself carries a location/store/branch column spanning more than one
    # value, since that's a real, deterministic signal a customer is
    # uploading combined multi-location data into a single business to
    # avoid the per-branch fee. Checked here, before any DB writes below,
    # so a blocked attempt makes zero changes and is cleanly re-triable —
    # explicit override (confirm_multiple_locations) lets a genuinely
    # single-location shop whose export happens to repeat a store name/code
    # push through anyway.
    location_column = field_mapping.get("location")
    if location_column is not None and not confirm_multiple_locations:
        locations = _distinct_location_values(grid, result, location_column)
        if len(locations) > 1:
            return ConfirmMappingResult(
                status="needs_location_confirmation",
                import_record=None,
                mapping_profile_id=None,
                locations=locations,
            )

    column_mapping = {
        "entity_type": upload.entity_type,
        "engine_version": 1,
        "fields": field_mapping,
        # Not authoritative for reuse — app/imports/importer.py re-detects
        # the header fresh on each import and only falls back to this if
        # that re-detection fails, which happens precisely for files that
        # needed a manual pick here in the first place.
        "header_row_index": result.header_row_index,
    }
    profile = ImportMappingProfileRepository(db).upsert(
        business_id=upload.business_id,
        source_signature=result.source_signature,
        column_mapping=column_mapping,
    )
    # No-op on a first-time confirm (nothing to delete yet). On a remap,
    # removes the previous attempt's record first — preserves "exactly one
    # ImportRecord per Upload" (get_for_upload/map_by_upload_id both assume
    # this), rather than leaving a stale "mapped, zero rows" row behind.
    ImportRecordRepository(db).delete_for_upload(upload.business_id, upload.id)
    record = ImportRecordRepository(db).create(
        business_id=upload.business_id,
        upload_id=upload.id,
        mapping_profile_id=profile.id,
        entity_type=upload.entity_type,
        status="mapped",
    )
    UploadRepository(db).set_status(upload, status="mapped")
    return ConfirmMappingResult(
        status="confirmed", import_record=record, mapping_profile_id=profile.id, locations=None
    )
