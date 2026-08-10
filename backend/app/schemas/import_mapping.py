import uuid

from pydantic import BaseModel


class FieldCandidateOut(BaseModel):
    source_column: str
    confidence: float
    source: str  # "alias" | "structural" (future: "ai")
    sample_values: list[str]

    # Populated from app/imports/detection.py's FieldCandidate dataclass,
    # not a dict, when the route builds DetectMappingResponse.
    model_config = {"from_attributes": True}


class DetectMappingRequest(BaseModel):
    # Set only on the retry after the user picks a row from preview_rows
    # (status "header_not_found") — omitted entirely for the normal,
    # auto-detected call.
    header_row_index: int | None = None


class DetectMappingResponse(BaseModel):
    status: str  # "reused" | "needs_confirmation" | "header_not_found"
    mapping_profile_id: uuid.UUID | None
    suggested_mapping: dict[str, str | None]
    # Every column actually in the file — lets the frontend offer any
    # column as an override, not just the algorithm's top candidates.
    columns: list[str]
    field_candidates: dict[str, list[FieldCandidateOut]]
    unmapped_columns: list[str]
    # Only set when status == "header_not_found": the first ~15 raw rows,
    # for a "click the header row" picker.
    preview_rows: list[list[str]] | None = None


class ConfirmMappingRequest(BaseModel):
    field_mapping: dict[str, str | None]
    # Must match whatever header_row_index the manual pick (if any) used
    # for detect-mapping — omitted for the normal auto-detected case.
    header_row_index: int | None = None
    # Set true only on the retry after the user has seen
    # "needs_location_confirmation" and explicitly confirmed this really
    # is one location (BD-007 anti-bypass check) — omitted (defaults
    # false) for every normal confirm-mapping call.
    confirm_multiple_locations: bool = False


class ConfirmMappingResponse(BaseModel):
    # Both None specifically when status == "needs_location_confirmation" —
    # nothing was created, the caller must resubmit with
    # confirm_multiple_locations=True (or fix the mapping) to get a real one.
    import_record_id: uuid.UUID | None
    mapping_profile_id: uuid.UUID | None
    status: str  # "mapped" | "needs_location_confirmation"
    # Only set when status == "needs_location_confirmation": the distinct
    # location values found, so the frontend can show what was detected
    # and point at "Add a branch".
    locations: list[str] | None = None
