import uuid
from datetime import datetime

from pydantic import BaseModel


class ImportRunResponse(BaseModel):
    import_record_id: uuid.UUID
    status: str
    rows_total: int
    rows_imported: int
    rows_rejected: int
    rejection_summary: dict | None


class ImportUndoResponse(BaseModel):
    import_record_id: uuid.UUID
    status: str
    reversed_at: datetime | None
