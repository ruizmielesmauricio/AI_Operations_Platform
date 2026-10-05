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
    # Prices/categories this file had overwritten on existing products that
    # undo put back (app/imports/revert.py), and how many it deliberately
    # left alone because a newer import or a manual edit has since changed
    # them — shown to the user so a revert is never silent.
    values_restored: int = 0
    values_kept: int = 0
