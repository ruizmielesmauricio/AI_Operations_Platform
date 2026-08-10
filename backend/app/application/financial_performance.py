"""Orchestrates the Financial Performance summary for a route: resolves the
reporting period, pulls raw numbers from the repositories, and feeds them
into the pure formulas in app/analytics/financial.py. No calculation logic
of its own — see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analytics.financial import (
    GrossMarginResult,
    ProductMarginRow,
    ReturnsSummary,
    RevenueTrend,
    compute_gross_margin,
    compute_returns_summary,
    compute_revenue_change,
    rank_products_by_margin,
)
from app.analytics.period import MetricPeriod, resolve_period
from app.models.business import Business
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.return_ import ReturnRepository
from app.repositories.sale import SaleRepository
from app.repositories.sale_item import SaleItemRepository

_TOP_N = 5


@dataclass(frozen=True)
class FinancialPerformanceSummary:
    period: MetricPeriod
    # The exact date range revenue.previous was computed over — live-
    # reported gap: a chat follow-up asking "what is the last/previous
    # period?" had no real dates anywhere in this payload to answer from,
    # only the previous period's revenue figure, so an honest answer
    # could say the number but never the actual dates. Was already
    # computed locally below (needed to run the previous-period query)
    # and simply never carried onto the summary before this.
    previous_period: MetricPeriod
    revenue: RevenueTrend
    gross_margin: GrossMarginResult
    top_margin_products: list[ProductMarginRow]
    bottom_margin_products: list[ProductMarginRow]
    products_excluded_from_ranking: int
    returns: ReturnsSummary
    # Every ranked product (not just the top/bottom-by-gross-profit
    # slices above) — internal only, deliberately not mirrored onto
    # FinancialPerformanceOut/the API payload (an unbounded per-product
    # list has no place on the wire). Feeds
    # app/analytics/findings.py::evaluate_thin_margin_high_revenue via
    # app/application/findings.py, which needs to re-rank by revenue
    # rather than gross profit.
    all_margin_products: list[ProductMarginRow]


def get_financial_performance(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    category_id: uuid.UUID | None = None,
) -> FinancialPerformanceSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, start_date, end_date)

    products = ProductRepository(db).list_for_business(business_id)
    if category_id is not None:
        products = [p for p in products if p.category_id == category_id]
    products_by_id = {product.id: product.name for product in products}

    # Direct request: show each product's category beside its name in
    # every product-row table, independent of whether a filter is active.
    category_name_by_id = {c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business_id)}
    category_name_by_product = {
        product.id: (category_name_by_id.get(product.category_id) if product.category_id else None)
        for product in products
    }

    aggregates = SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    previous_period = period.previous()
    previous_aggregates = SaleItemRepository(db).aggregate_by_product_in_range(
        business_id, previous_period.start, previous_period.end
    )

    if category_id is not None:
        # aggregate_by_product_in_range has no category filter of its own
        # (no Product join — see its own docstring), so both periods'
        # results are constrained here before anything downstream runs —
        # every existing formula (compute_gross_margin, rank_products_by_
        # margin) is reused completely unmodified, just over the smaller
        # set. Revenue can no longer be read off SaleRepository.
        # sum_total_amount_in_range below (that's a whole-Sale total, not
        # attributable to one category when a sale spans several) — it's
        # derived instead from the now-filtered per-product aggregates,
        # the same revenue figure app/analytics/category.py already uses.
        aggregates = [a for a in aggregates if a.product_id in products_by_id]
        previous_aggregates = [a for a in previous_aggregates if a.product_id in products_by_id]
        current_revenue = sum((a.revenue for a in aggregates), Decimal("0"))
        previous_revenue = sum((a.revenue for a in previous_aggregates), Decimal("0"))
    else:
        sale_repo = SaleRepository(db)
        current_revenue = sale_repo.sum_total_amount_in_range(business_id, period.start, period.end)
        previous_revenue = sale_repo.sum_total_amount_in_range(business_id, previous_period.start, previous_period.end)

    revenue_trend = compute_revenue_change(current_revenue, previous_revenue)
    gross_margin = compute_gross_margin(aggregates)

    top, bottom, excluded_count, all_margin_products = rank_products_by_margin(
        aggregates, products_by_id, top_n=_TOP_N, category_name_by_product=category_name_by_product
    )

    # Returns are NOT category-scoped even when category_id is set — a
    # deliberate, stated scope limit: Return only links to SaleItem/Sale,
    # and ReturnRepository has no product/category-aware query today.
    # Concretely: returns_amount/return_count below are always whole-
    # business figures, combined here with a possibly category-scoped
    # current_revenue — under a category filter, the resulting
    # gross_revenue/return_rate_pct are therefore not strictly accurate
    # for that category (a low-revenue category could show an inflated
    # rate against whole-business returns). Not solved here; building a
    # real Return -> SaleItem -> Product join was out of scope for what
    # was actually requested (revenue/expenses/stock value by category).
    return_repo = ReturnRepository(db)
    returns_amount = return_repo.sum_refund_amount_in_range(business_id, period.start, period.end)
    return_count = return_repo.count_in_range(business_id, period.start, period.end)
    returns_summary = compute_returns_summary(current_revenue, returns_amount, return_count)

    return FinancialPerformanceSummary(
        period=period,
        previous_period=previous_period,
        revenue=revenue_trend,
        gross_margin=gross_margin,
        top_margin_products=top,
        bottom_margin_products=bottom,
        products_excluded_from_ranking=excluded_count,
        returns=returns_summary,
        all_margin_products=all_margin_products,
    )
