"""Stage D17/D18's scheduler tick: one reconciliation pass that serves as
scheduling (PR-8.1/8.2), retry (PR-8.9), and missed-report recovery
(PR-8.10) all at once — see app/application/report.py::generate_report's
docstring for why a single idempotent "try to generate what's due and
missing" mechanism covers all three, rather than three separate systems.
No AI, no calculation logic here — purely deciding *when* to call an
existing, already-tested generation function.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.period import compute_report_period, is_report_period_due, resolve_period
from app.application.notifications import notify_orla_insights, notify_report_failed, notify_report_ready
from app.application.report import generate_report
from app.models.business import Business
from app.repositories.report import MAX_ATTEMPTS, ReportRepository

logger = logging.getLogger(__name__)

REPORT_TYPES = ("weekly", "monthly")


def run_tick(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """One reconciliation pass across every business and both report
    types. Never raises — a single business or report type failing must
    not stop the rest of the pass from being checked (same "don't let one
    failure take down the whole batch" principle as
    app/application/alerts.py::refresh_low_stock_alerts's own try/except
    wrapping). Returns small counts, purely for logging/tests — callers
    don't need to branch on them.
    """
    resolved_now = now or datetime.now(timezone.utc)
    report_repo = ReportRepository(db)
    generated = 0
    already_done = 0
    permanently_failed = 0
    not_yet_due = 0

    businesses = list(db.scalars(select(Business)))
    for business in businesses:
        for report_type in REPORT_TYPES:
            try:
                start_date, end_date = compute_report_period(business.timezone, report_type, now=resolved_now)
                if not is_report_period_due(business.timezone, end_date, now=resolved_now):
                    not_yet_due += 1
                    continue

                period = resolve_period(business.timezone, start_date, end_date)
                existing = report_repo.get_by_period(business.id, report_type, period.start)
                if existing is not None and existing.status == "completed":
                    already_done += 1
                    continue
                if existing is not None and existing.status == "failed" and existing.attempts >= MAX_ATTEMPTS:
                    # PR-8.11's "alert the operator" — no real alerting
                    # channel exists anywhere else in this codebase yet
                    # either, so this stays consistent with that rather
                    # than inventing one just for reports. The row itself
                    # (status, attempts, last_error, timestamps) is the
                    # operational audit record PR-8.12 asks for.
                    logger.error(
                        "Report permanently failed after %s attempts: business=%s type=%s "
                        "period_start=%s last_error=%s",
                        existing.attempts,
                        business.id,
                        report_type,
                        period.start,
                        existing.last_error,
                    )
                    permanently_failed += 1
                    try:
                        notify_report_failed(db, business_id=business.id, report_type=report_type, period_start=start_date)
                        db.commit()
                    except Exception:
                        logger.exception("Failed to create report-failed notification: business=%s type=%s", business.id, report_type)
                    continue

                report = generate_report(db, business_id=business.id, report_type=report_type, now=resolved_now)
                if report.status == "completed":
                    generated += 1
                    logger.info(
                        "Generated report business=%s type=%s period_start=%s", business.id, report_type, period.start
                    )
                    try:
                        notify_report_ready(
                            db, business_id=business.id, report_id=report.id, report_type=report_type,
                            period_start=start_date, period_end=end_date,
                        )
                        recommendation_count = len(report.payload.get("findings", {}).get("recommendations", []))
                        notify_orla_insights(
                            db, business_id=business.id, report_id=report.id, recommendation_count=recommendation_count
                        )
                        db.commit()
                    except Exception:
                        logger.exception("Failed to create report-ready notification: business=%s type=%s", business.id, report_type)
                # A "failed" result here (attempts just incremented, still
                # under the cap) is deliberately not logged again —
                # generate_report already logged the exception itself.
            except Exception:
                # Broad and deliberate: an unexpected error checking one
                # business/report_type combination must never abort the
                # rest of this tick's pass over every other business.
                logger.exception("Unexpected error checking business=%s type=%s", business.id, report_type)

    return {
        "generated": generated,
        "already_done": already_done,
        "permanently_failed": permanently_failed,
        "not_yet_due": not_yet_due,
    }
