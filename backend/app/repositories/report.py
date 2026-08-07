import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.report import Report

# Past this many failed attempts, app/scheduler/tick.py stops retrying and
# just logs loudly (PR-8.11's "alert the operator" — no real alerting
# channel exists anywhere else in this codebase yet either, so this stays
# consistent with that rather than inventing one just for reports).
MAX_ATTEMPTS = 5


class ReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_for_business(self, report_id: uuid.UUID, business_id: uuid.UUID) -> Report | None:
        return self.session.scalar(
            select(Report).where(Report.id == report_id, Report.business_id == business_id)
        )

    def get_by_period(self, business_id: uuid.UUID, report_type: str, period_start: datetime) -> Report | None:
        """The idempotency pre-check app/scheduler/tick.py's reconciliation
        loop uses before attempting generation — belt-and-suspenders
        alongside the DB unique constraint (PR-8.8), which is what
        actually guarantees it under a race."""
        return self.session.scalar(
            select(Report).where(
                Report.business_id == business_id,
                Report.report_type == report_type,
                Report.period_start == period_start,
            )
        )

    def list_active_for_business(self, business_id: uuid.UUID, *, now: datetime) -> list[Report]:
        """Completed, not-yet-expired reports, newest period first — the
        customer-facing list (PR-8.5's "available for seven days"). A
        report past its expiry isn't deleted (it stays as its own
        operational audit record, PR-8.12) — it's just excluded here."""
        return list(
            self.session.scalars(
                select(Report)
                .where(
                    Report.business_id == business_id,
                    Report.status == "completed",
                    Report.expires_at.isnot(None),
                    Report.expires_at > now,
                )
                .order_by(Report.period_start.desc())
            )
        )

    def create_pending(
        self, *, business_id: uuid.UUID, report_type: str, period_start: datetime, period_end: datetime
    ) -> Report:
        # Committed immediately, not flush-only — this row's own existence
        # is what makes a concurrent/retried tick see "generation is
        # already under way" for this period, and its own the source of
        # truth if the process crashes mid-generation (the next tick finds
        # a "pending" row with 0 completed attempts and retries it).
        report = Report(
            business_id=business_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            status="pending",
        )
        self.session.add(report)
        self.session.commit()
        self.session.refresh(report)
        return report

    def mark_completed(self, report: Report, *, payload: dict, expires_at: datetime) -> Report:
        report.status = "completed"
        report.payload = payload
        report.expires_at = expires_at
        self.session.commit()
        return report

    def mark_failed(self, report: Report, *, error_message: str) -> Report:
        report.status = "failed"
        report.attempts += 1
        report.last_error = error_message[:1024]
        self.session.commit()
        return report
