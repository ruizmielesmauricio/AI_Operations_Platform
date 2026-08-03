"""Orchestrates the ingestion pipeline's upload and detection steps (PR-2,
ADR-008). Route handlers stay thin (CLAUDE.md) — this is where that logic
lives, one level above the R2 SDK boundary in app/imports/r2_client.py.
"""

import os
import uuid
from dataclasses import dataclass, field as dataclass_field

from sqlalchemy.orm import Session

from app.imports import detection, file_parser, r2_client
from app.imports.aliases import CANONICAL_FIELDS, SUPPORTED_ENTITY_TYPES
from app.imports.detection import FieldCandidate
from app.imports.exceptions import (
    FileTooLarge,
    InsufficientMapping,
    InvalidFieldMapping,
    UnsupportedEntityType,
    UnsupportedFileType,
    UploadNotReady,
)
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
class DetectMappingResult:
    status: str  # "reused" | "needs_confirmation"
    mapping_profile_id: uuid.UUID | None
    suggested_mapping: dict[str, str | None]
    columns: list[str] = dataclass_field(default_factory=list)
    field_candidates: dict[str, list[FieldCandidate]] = dataclass_field(default_factory=dict)
    unmapped_columns: list[str] = dataclass_field(default_factory=list)


def download_checked(storage_key: str) -> bytes:
    """Shared with app/imports/importer.py — same 20MB guard for both
    detection (bounded read) and the full import (needs every row)."""
    size = r2_client.get_object_size(storage_key=storage_key)
    if size > _MAX_DETECTION_FILE_SIZE_BYTES:
        raise FileTooLarge(size, _MAX_DETECTION_FILE_SIZE_BYTES)
    return r2_client.download_object(storage_key=storage_key)


def _detect(upload: Upload) -> detection.DetectionResult:
    file_bytes = download_checked(upload.storage_key)
    grid = file_parser.read_rows(file_bytes, upload.original_filename, max_rows=_DETECTION_WINDOW_ROWS)
    return detection.detect_mapping(grid, upload.entity_type)


def detect_mapping_for_upload(db: Session, upload: Upload) -> DetectMappingResult:
    if upload.status != "uploaded":
        raise UploadNotReady(upload.status)

    result = _detect(upload)
    columns = [c for c in result.columns if c]
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


def confirm_mapping(
    db: Session, upload: Upload, field_mapping: dict[str, str | None]
) -> tuple[ImportRecord, uuid.UUID]:
    if upload.status != "uploaded":
        raise UploadNotReady(upload.status)

    # Re-run detection rather than trust the client's payload shape/columns
    # past the membership check — a stale frontend or tampered request must
    # fail loudly, not silently under-map or reference a column that isn't
    # actually in this file.
    result = _detect(upload)
    canonical_fields = set(CANONICAL_FIELDS[upload.entity_type])
    if set(field_mapping.keys()) != canonical_fields:
        raise InvalidFieldMapping("field_mapping must include exactly the canonical fields for this entity type")
    valid_columns = set(result.columns)
    for column in field_mapping.values():
        if column is not None and column not in valid_columns:
            raise InvalidFieldMapping(f"'{column}' is not a column in this file")

    if not field_mapping.get("sale_date") or not (
        field_mapping.get("unit_price") or field_mapping.get("total_amount")
    ):
        raise InsufficientMapping()

    column_mapping = {"entity_type": upload.entity_type, "engine_version": 1, "fields": field_mapping}
    profile = ImportMappingProfileRepository(db).upsert(
        business_id=upload.business_id,
        source_signature=result.source_signature,
        column_mapping=column_mapping,
    )
    record = ImportRecordRepository(db).create(
        business_id=upload.business_id,
        upload_id=upload.id,
        mapping_profile_id=profile.id,
        status="mapped",
    )
    UploadRepository(db).set_status(upload, status="mapped")
    return record, profile.id
