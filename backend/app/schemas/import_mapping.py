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


class DetectMappingResponse(BaseModel):
    status: str  # "reused" | "needs_confirmation"
    mapping_profile_id: uuid.UUID | None
    suggested_mapping: dict[str, str | None]
    # Every column actually in the file — lets the frontend offer any
    # column as an override, not just the algorithm's top candidates.
    columns: list[str]
    field_candidates: dict[str, list[FieldCandidateOut]]
    unmapped_columns: list[str]


class ConfirmMappingRequest(BaseModel):
    field_mapping: dict[str, str | None]


class ConfirmMappingResponse(BaseModel):
    import_record_id: uuid.UUID
    mapping_profile_id: uuid.UUID
    status: str
