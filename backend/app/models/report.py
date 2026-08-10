from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Report(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A generated weekly or monthly report (PR-8, PD-007, ADR-019).
    Uniquely keyed by (business_id, report_type, period_start) — a real DB
    constraint, not just an application-layer convention — to make
    generation idempotent (PR-8.8): the scheduler tick
    (app/scheduler/tick.py) simply relies on the insert failing if it ever
    raced with itself.

    status: "pending" (row created, generation in progress) ->
    "completed" (payload populated, expires_at set) or "failed" (attempts
    incremented, last_error recorded — the tick retries a failed row on
    its next pass, up to a small cap). A row is never hard-deleted, even
    after expiry — it's its own operational audit record (PR-8.12);
    read paths just filter out anything past expires_at.
    """

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "report_type", "period_start", name="uq_reports_business_id_report_type_period_start"
        ),
    )

    report_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "weekly" | "monthly"
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
