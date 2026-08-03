import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    # A plain str (not a Pydantic Literal) validated in app/imports/service.py
    # against SUPPORTED_ENTITY_TYPES — same pattern as file-extension
    # validation, so both live in one place as the entity-type set grows.
    entity_type: str = Field(min_length=1, max_length=32)


class UploadCreateResponse(BaseModel):
    id: uuid.UUID
    upload_url: str


class ImportRecordSummary(BaseModel):
    id: uuid.UUID
    status: str
    rows_total: int
    rows_imported: int
    rows_rejected: int
    rejection_summary: dict | None
    reversed_at: datetime | None

    model_config = {"from_attributes": True}


class UploadOut(BaseModel):
    id: uuid.UUID
    original_filename: str
    entity_type: str
    status: str
    created_at: datetime
    # None until a mapping's been confirmed — lets the frontend know
    # whether to show "Map columns", "Run import", or the import summary
    # + "Undo" without a separate round-trip per upload.
    import_record: ImportRecordSummary | None = None

    model_config = {"from_attributes": True}
