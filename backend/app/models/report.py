from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Report(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A generated weekly or monthly report (PR-8, PD-007, ADR-019).
    Uniquely keyed by (business_id, report_type, period_start) at the
    application layer to make generation idempotent.
    """

    __tablename__ = "reports"

    report_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "weekly" | "monthly"
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
