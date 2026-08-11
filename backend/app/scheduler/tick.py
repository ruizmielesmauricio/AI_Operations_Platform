"""Stage D17/D18's scheduler tick: one reconciliation pass that serves as
scheduling (PR-8.1/8.2), retry (PR-8.9), and missed-report recovery
(PR-8.10) all at once — see app/application/report.py::generate_report's
docstring for why a single idempotent "try to generate what's due and
missing" mechanism covers all three, rather than three separate systems.
No AI, no calculation logic here — purely deciding *when* to call an
existing, already-tested generation function.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.period import (
    compute_report_period,
    is_report_period_due,
    report_generation_moment,
    resolve_period,
)
from app.application.notifications import (
    AI_HEALTH_LOOKBACK_MINUTES,
    REPORT_DELAYED_AFTER_HOURS,
    check_data_freshness,
    is_ai_provider_likely_down,
    notify_ai_insights_unavailable,
    notify_orla_insights,
    notify_report_delayed,
    notify_report_failed,
    notify_report_ready,
    notify_stock_review,
    notify_weekly_business_performance,
    resolve_report_delayed,
)
from app.application.report import generate_report
from app.application.stock_review import get_stock_review
from app.models.business import Business
from app.repositories.ai_request import AIRequestRepository
from app.repositories.report import MAX_ATTEMPTS, ReportRepository
from app.repositories.sale import SaleRepository
from app.repositories.subscription import SubscriptionRepository

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
    subscriptions = SubscriptionRepository(db)
    freshness_checked = 0

    # One platform-wide read, not per-business — "is the AI provider
    # itself currently down" has exactly one true answer per tick, not
    # one per business (see is_ai_provider_likely_down's own docstring).
    ai_health_window_start = resolved_now - timedelta(minutes=AI_HEALTH_LOOKBACK_MINUTES)
    ai_provider_down = is_ai_provider_likely_down(
        AIRequestRepository(db).recent_platform_wide_success_flags(since=ai_health_window_start)
    )

    for business in businesses:
        # Scoped to active-subscription businesses only — a business that
        # never subscribed, or whose subscription has lapsed, can't even
        # upload (require_active_subscription already blocks that route),
        # so nudging it to "upload today's sales data" would be pure
        # noise, not a real reminder. Matches the ORLA Notification
        # Centre's own "when expected" framing.
        subscription = subscriptions.get_by_business_id(business.id)
        if subscription is not None and subscription.status == "active":
            try:
                check_data_freshness(db, business=business, now=resolved_now)
                db.commit()
                freshness_checked += 1
            except Exception:
                logger.exception("Failed to check data freshness for business=%s", business.id)
            try:
                notify_ai_insights_unavailable(db, business_id=business.id, is_down=ai_provider_down)
                db.commit()
            except Exception:
                logger.exception("Failed to check AI provider health for business=%s", business.id)

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
                        # Supersedes any open "delayed" notice for this
                        # same period — report_failed above already tells
                        # the real, final story now.
                        resolve_report_delayed(db, business_id=business.id, report_type=report_type, period_start=start_date)
                        db.commit()
                    except Exception:
                        logger.exception("Failed to create report-failed notification: business=%s type=%s", business.id, report_type)
                    continue

                # Still due, not yet completed, not yet permanently failed
                # — either a first attempt or a retry still under the cap.
                # "Materially delayed" / "stuck beyond a defined timeout"
                # (ORLA Notifications/Security/Retention prompt, section
                # 3) — a report that's *still* not done well past its own
                # due moment, independent of whether generate_report below
                # succeeds on this particular attempt.
                try:
                    due_moment = report_generation_moment(business.timezone, end_date)
                    if resolved_now >= due_moment + timedelta(hours=REPORT_DELAYED_AFTER_HOURS):
                        notify_report_delayed(db, business_id=business.id, report_type=report_type, period_start=start_date)
                        db.commit()
                except Exception:
                    logger.exception("Failed to check report delay for business=%s type=%s", business.id, report_type)

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
                        # Supersedes any open "delayed" notice for this
                        # same period — report_ready above already tells
                        # the real, final (successful) story now.
                        resolve_report_delayed(db, business_id=business.id, report_type=report_type, period_start=start_date)
                        recommendation_count = len(report.payload.get("findings", {}).get("recommendations", []))
                        notify_orla_insights(
                            db, business_id=business.id, report_id=report.id, recommendation_count=recommendation_count
                        )
                        # Weekly-only (ORLA Notifications/Security/Retention
                        # prompt, sections 1+2) — this codebase has no
                        # separate "Monday stock processing" job the way
                        # the prompt's own wording assumes; stock is
                        # already computed live from InventoryMovement on
                        # every read, so the weekly report's own Monday
                        # generation (already idempotent per period, see
                        # generate_report's docstring) is the one real
                        # "once a week" trigger point to hang both of
                        # these new notifications on, rather than
                        # inventing a second scheduling mechanism.
                        if report_type == "weekly":
                            revenue = report.payload.get("financial_performance", {}).get("revenue", {})
                            revenue_current = Decimal(revenue.get("current", "0"))
                            revenue_previous = Decimal(revenue.get("previous", "0"))
                            change_pct_raw = revenue.get("change_pct")
                            revenue_change_pct = Decimal(change_pct_raw) if change_pct_raw is not None else None
                            earliest_sale = SaleRepository(db).earliest_sale_date(business.id)
                            earliest_sale_date = (
                                earliest_sale.astimezone(ZoneInfo(business.timezone)).date()
                                if earliest_sale is not None
                                else None
                            )
                            notify_weekly_business_performance(
                                db, business_id=business.id, report_id=report.id, period_start=start_date,
                                revenue_current=revenue_current, revenue_previous=revenue_previous,
                                revenue_change_pct=revenue_change_pct, earliest_sale_date=earliest_sale_date,
                            )

                            stock_review = get_stock_review(db, business_id=business.id, now=resolved_now)
                            notify_stock_review(
                                db, business_id=business.id, week_start=start_date,
                                out_of_stock_count=stock_review.out_of_stock_count,
                                stale_count=stock_review.stale_count, excess_count=stock_review.excess_count,
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
        "freshness_checked": freshness_checked,
    }
