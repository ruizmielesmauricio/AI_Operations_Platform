import uuid
from datetime import datetime

from pydantic import BaseModel


class ReportSummaryOut(BaseModel):
    """The list view (GET .../reports) — deliberately excludes the full
    payload, which can be large; the detail route returns that."""

    id: uuid.UUID
    report_type: str
    period_start: datetime
    period_end: datetime
    status: str
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class ReportDetailOut(BaseModel):
    id: uuid.UUID
    report_type: str
    period_start: datetime
    period_end: datetime
    status: str
    created_at: datetime
    expires_at: datetime | None
    # The full assembled content (app/application/report.py's payload) —
    # already JSON-safe (Decimal serialized to str throughout), so this is
    # passed straight through, not re-modeled field by field.
    payload: dict | None

    model_config = {"from_attributes": True}
