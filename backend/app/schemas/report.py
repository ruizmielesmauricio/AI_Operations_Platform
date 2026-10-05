import uuid
from datetime import datetime

from pydantic import BaseModel, computed_field

from app.analytics.report_expiry import is_expiring_soon, seconds_until_expiry


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

    # Server-computed countdown (app/analytics/report_expiry.py) — one
    # clock for every viewer, and identical for weekly and monthly
    # reports (both expire seven days after generation, ADR-019).
    @computed_field  # type: ignore[prop-decorator]
    @property
    def seconds_until_expiry(self) -> int | None:
        return seconds_until_expiry(self.expires_at)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def expiring_soon(self) -> bool:
        return is_expiring_soon(seconds_until_expiry(self.expires_at))

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

    # Server-computed countdown (app/analytics/report_expiry.py) — one
    # clock for every viewer, and identical for weekly and monthly
    # reports (both expire seven days after generation, ADR-019).
    @computed_field  # type: ignore[prop-decorator]
    @property
    def seconds_until_expiry(self) -> int | None:
        return seconds_until_expiry(self.expires_at)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def expiring_soon(self) -> bool:
        return is_expiring_soon(seconds_until_expiry(self.expires_at))

    model_config = {"from_attributes": True}
