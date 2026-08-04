"""Orchestrates the Financial Performance summary for a route: resolves the
reporting period, pulls raw numbers from the repositories, and feeds them
into the pure formulas in app/analytics/financial.py. No calculation logic
of its own — see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.analytics.financial import (
    GrossMarginResult,
    ProductMarginRow,
    RevenueTrend,
    compute_gross_margin,
    compute_revenue_change,
    rank_products_by_margin,
)
from app.analytics.period import MetricPeriod, resolve_period
from app.models.business import Business
from app.repositories.product import ProductRepository
from app.repositories.sale import SaleRepository
from app.repositories.sale_item import SaleItemRepository

_TOP_N = 5


@dataclass(frozen=True)
class FinancialPerformanceSummary:
    period: MetricPeriod
    revenue: RevenueTrend
    gross_margin: GrossMarginResult
    top_margin_products: list[ProductMarginRow]
    bottom_margin_products: list[ProductMarginRow]
    products_excluded_from_ranking: int


def get_financial_performance(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> FinancialPerformanceSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, start_date, end_date)

    sale_repo = SaleRepository(db)
    current_revenue = sale_repo.sum_total_amount_in_range(business_id, period.start, period.end)
    previous_period = period.previous()
    previous_revenue = sale_repo.sum_total_amount_in_range(business_id, previous_period.start, previous_period.end)
    revenue_trend = compute_revenue_change(current_revenue, previous_revenue)

    aggregates = SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    gross_margin = compute_gross_margin(aggregates)

    products_by_id = {product.id: product.name for product in ProductRepository(db).list_for_business(business_id)}
    top, bottom, excluded_count = rank_products_by_margin(aggregates, products_by_id, top_n=_TOP_N)

    return FinancialPerformanceSummary(
        period=period,
        revenue=revenue_trend,
        gross_margin=gross_margin,
        top_margin_products=top,
        bottom_margin_products=bottom,
        products_excluded_from_ranking=excluded_count,
    )
