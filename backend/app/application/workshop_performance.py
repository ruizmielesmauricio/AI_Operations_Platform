"""Orchestrates the Workshop Performance summary for a route: resolves the
reporting period, pulls raw repair totals from the repository, and feeds
them into the pure formulas in app/analytics/workshop.py. No calculation
logic of its own — see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.analytics.financial import RevenueTrend, compute_revenue_change
from app.analytics.period import MetricPeriod, resolve_period
from app.analytics.workshop import WorkshopMarginResult, compute_workshop_margin
from app.models.business import Business
from app.repositories.production_event import ProductionEventRepository


@dataclass(frozen=True)
class WorkshopPerformanceSummary:
    period: MetricPeriod
    revenue: RevenueTrend
    margin: WorkshopMarginResult


def get_workshop_performance(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> WorkshopPerformanceSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, start_date, end_date)
    repo = ProductionEventRepository(db)

    totals = repo.aggregate_completed_repairs_in_range(business_id, period.start, period.end)
    margin = compute_workshop_margin(totals)

    previous_period = period.previous()
    previous_totals = repo.aggregate_completed_repairs_in_range(business_id, previous_period.start, previous_period.end)
    # Reuses financial.py's revenue-trend formula as-is — "current vs
    # previous period revenue" is the same computation regardless of which
    # domain the revenue came from.
    revenue_trend = compute_revenue_change(totals.revenue, previous_totals.revenue)

    return WorkshopPerformanceSummary(period=period, revenue=revenue_trend, margin=margin)
