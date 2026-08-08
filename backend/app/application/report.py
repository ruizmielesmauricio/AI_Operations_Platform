"""Orchestrates Stage D17/D18's scheduled report generation: resolves the
report's period, assembles a JSON payload entirely from existing C9-C13
application-layer functions, and persists it via ReportRepository. No
calculation logic of its own, and no AI anywhere (PR-8.7 — "all numbers,
summaries, projections, and recommendations trace to backend
calculations, templates, or rules") — this module's only job is
assembly, reusing exactly what the dashboard already computes and
serves.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.analytics.period import compute_report_period, resolve_period
from app.analytics.report_narrative import build_executive_narrative
from app.analytics.retail import classify_movers, compute_inventory_turnover
from app.application.category_breakdown import get_category_breakdown
from app.application.financial_performance import get_financial_performance
from app.application.findings import get_findings
from app.application.forecast import get_forecast
from app.application.retail_operations import get_retail_operations
from app.application.workshop_performance import get_workshop_performance
from app.models.business import Business
from app.models.report import Report
from app.repositories.alert import AlertRepository
from app.repositories.report import ReportRepository
from app.repositories.sale import SaleRepository
from app.schemas.analytics import (
    CategoryBreakdownOut,
    FinancialPerformanceOut,
    FindingsOut,
    ForecastOut,
    RecommendationOut,
    RetailOperationsOut,
    StockCoverOut,
    WorkshopPerformanceOut,
)

logger = logging.getLogger(__name__)

_REPORT_EXPIRY_DAYS = 7
_WEEKLY_FORECAST_HORIZON_DAYS = 7
_MONTHLY_FORECAST_HORIZON_DAYS = 30
_TOP_RECOMMENDATIONS_IN_SUMMARY = 5
_CENTS = Decimal("0.01")


def generate_report(
    db: Session, *, business_id: uuid.UUID, report_type: str, now: datetime | None = None
) -> Report:
    """Idempotent (PR-8.8): if a completed report already exists for this
    (business, report_type, period), returns it unchanged rather than
    regenerating. Reuses a "pending"/"failed" row from a previous attempt
    rather than creating a new one — the unique constraint on
    (business_id, report_type, period_start) would reject a second row
    for the same period anyway. This one function, called repeatedly, is
    how retry (PR-8.9) and missed-report recovery (PR-8.10) both work —
    app/scheduler/tick.py just calls it again on the next pass for
    whatever's still not "completed."
    """
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    resolved_now = now or datetime.now(timezone.utc)
    start_date, end_date = compute_report_period(business.timezone, report_type, now=resolved_now)
    period = resolve_period(business.timezone, start_date, end_date)

    report_repo = ReportRepository(db)
    report = report_repo.get_by_period(business_id, report_type, period.start)
    if report is not None and report.status == "completed":
        return report
    if report is None:
        report = report_repo.create_pending(
            business_id=business_id, report_type=report_type, period_start=period.start, period_end=period.end
        )

    try:
        payload = _assemble_payload(
            db, business=business, report_type=report_type, start_date=start_date, end_date=end_date, now=resolved_now
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad: must never crash the caller's reconciliation loop
        logger.exception(
            "Report generation failed for business=%s type=%s period_start=%s", business_id, report_type, period.start
        )
        return report_repo.mark_failed(report, error_message=str(exc))

    expires_at = resolved_now + timedelta(days=_REPORT_EXPIRY_DAYS)
    return report_repo.mark_completed(report, payload=payload, expires_at=expires_at)


def _assemble_payload(
    db: Session, *, business: Business, report_type: str, start_date: date, end_date: date, now: datetime
) -> dict:
    financial = get_financial_performance(db, business_id=business.id, start_date=start_date, end_date=end_date)
    retail = get_retail_operations(db, business_id=business.id, start_date=start_date, end_date=end_date)
    findings = get_findings(db, business_id=business.id, start_date=start_date, end_date=end_date)
    # Direct request: a reports table breaking down revenue/expenses/stock
    # value per category — never filtered (unlike the dashboard's
    # per-section dropdowns), a report always shows every category.
    category_breakdown = get_category_breakdown(db, business_id=business.id, start_date=start_date, end_date=end_date)

    horizon_days = _WEEKLY_FORECAST_HORIZON_DAYS if report_type == "weekly" else _MONTHLY_FORECAST_HORIZON_DAYS
    forecast = get_forecast(db, business_id=business.id, horizon_days=horizon_days, now=now)

    # Business-specific section — omitted entirely (never a misleading
    # placeholder) for any template with no section built for it yet, per
    # PR-8.3's own "sections that do not apply ... are omitted" rule.
    # Bike Shop (repairs) is the only one with real data behind it today;
    # Pharmacy near-expiry needs an inventory_lots writer that doesn't
    # exist yet (ADR-022) — deliberately not attempted here.
    workshop = None
    if business.template == "bicycle_shop":
        workshop = get_workshop_performance(db, business_id=business.id, start_date=start_date, end_date=end_date)

    sale_rows = SaleRepository(db).list_amounts_in_range(business.id, financial.period.start, financial.period.end)
    transaction_count = len(sale_rows)
    average_sale = (
        (financial.revenue.current / transaction_count).quantize(_CENTS, rounding=ROUND_HALF_UP)
        if transaction_count
        else None
    )

    # Reuses the same persisted alerts a user already sees on the
    # dashboard (Stage C12) rather than re-deriving threshold logic here —
    # one source of truth for "how many products are low on stock right now."
    low_stock_count = len(
        [a for a in AlertRepository(db).list_active_for_business(business.id) if a.alert_type == "low_stock"]
    )
    dead_stock_count = len(retail.dead_stock)
    movers = classify_movers(retail.stock_cover)
    turnover = compute_inventory_turnover(financial.gross_margin.cogs, retail.inventory_value.value_at_cost)

    top_recommendation = findings.recommendations[0] if findings.recommendations else None
    narrative = build_executive_narrative(
        revenue=financial.revenue,
        low_stock_count=low_stock_count,
        dead_stock_count=dead_stock_count,
        top_recommendation_title=top_recommendation.title if top_recommendation else None,
    )

    return {
        "business_name": business.name,
        "business_type": business.template,
        "report_type": report_type,
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "generated_at": now.isoformat(),
        "executive_summary": {
            "narrative": narrative,
            "transactions": transaction_count,
            "average_sale": str(average_sale) if average_sale is not None else None,
            "low_stock_count": low_stock_count,
            "dead_stock_count": dead_stock_count,
            "top_recommendations": [
                RecommendationOut.model_validate(r).model_dump(mode="json")
                for r in findings.recommendations[:_TOP_RECOMMENDATIONS_IN_SUMMARY]
            ],
        },
        # Reuses the exact same Pydantic schemas the dashboard API already
        # serves — same shape, same Decimal-as-string precision (verified:
        # Pydantic's mode="json" serializes Decimal to str, never float),
        # so a report and the live dashboard can never silently disagree
        # about what a number means.
        "financial_performance": FinancialPerformanceOut.model_validate(financial).model_dump(mode="json"),
        "retail_operations": RetailOperationsOut.model_validate(retail).model_dump(mode="json"),
        "inventory_health": {
            "fast_movers": [StockCoverOut.model_validate(r).model_dump(mode="json") for r in movers.fast_movers],
            "slow_movers": [StockCoverOut.model_validate(r).model_dump(mode="json") for r in movers.slow_movers],
            "turnover_ratio": str(turnover) if turnover is not None else None,
        },
        "forecast": ForecastOut.model_validate(forecast).model_dump(mode="json"),
        "findings": FindingsOut.model_validate(findings).model_dump(mode="json"),
        "category_breakdown": CategoryBreakdownOut.model_validate(category_breakdown).model_dump(mode="json"),
        "workshop_performance": (
            WorkshopPerformanceOut.model_validate(workshop).model_dump(mode="json") if workshop is not None else None
        ),
    }
