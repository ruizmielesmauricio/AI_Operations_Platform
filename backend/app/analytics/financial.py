"""Financial Performance / Profitability formulas (02_Operational_Domains.md
domain 3, PR-3). Pure — every function here takes plain Decimal/dataclass
inputs and returns a result, no DB session, no I/O. Unit-tested directly in
tests/unit/test_financial_analytics.py per ED-007.

Per CLAUDE.md ("Decimal for money, never float") and the rounding
convention established in app/imports/importer.py, every money/percentage
result is quantized before being returned rather than left as a raw
division result.
"""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.analytics.types import ProductPeriodAggregate

_CENTS = Decimal("0.01")
_TENTH_PERCENT = Decimal("0.1")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(_TENTH_PERCENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class GrossMarginResult:
    # Total revenue in the period, cost-known or not — kept alongside the
    # cost-known slices below so a caller can compute "how much revenue is
    # NOT covered by cost data" (total_revenue - revenue_with_known_cost)
    # directly, without reconstructing it via cost_data_coverage_pct
    # division (which breaks at 0% coverage). Stage C10's
    # incomplete_cost_data finding uses this.
    total_revenue: Decimal
    revenue_with_known_cost: Decimal
    cogs: Decimal
    gross_profit: Decimal
    # None when revenue_with_known_cost is 0 — nothing to divide by, and
    # "0% margin" would misleadingly read as "no profit" rather than "no
    # cost data".
    gross_margin_pct: Decimal | None
    # revenue_with_known_cost / total revenue, as a percentage — the PR-3.5
    # "data completeness" flag for this metric. 100 means every line item
    # in the period had a cost_price_at_sale recorded.
    cost_data_coverage_pct: Decimal | None
    # Margin computed net of tax, over only the lines where BOTH cost and
    # tax are known (a stricter subset of revenue_with_known_cost/gross_profit
    # above) — never blends a tax-unknown line (whose revenue may still
    # include tax) into a "confirmed net" figure. None when no line has
    # both known; this is the number the dashboard prefers to show
    # whenever it's available, since gross_margin_pct above may overstate
    # margin for any revenue sourced from a tax-inclusive total.
    net_gross_profit: Decimal | None = None
    net_gross_margin_pct: Decimal | None = None
    # revenue_with_known_cost_and_tax / revenue_with_known_cost, as a
    # percentage — the completeness flag for net_gross_margin_pct
    # specifically (same role as cost_data_coverage_pct, one level
    # stricter). None when revenue_with_known_cost is 0.
    tax_data_coverage_pct: Decimal | None = None


@dataclass(frozen=True)
class RevenueTrend:
    current: Decimal
    previous: Decimal
    # None when previous is 0 — division by zero, and "infinite growth"
    # isn't a number worth displaying.
    change_pct: Decimal | None


@dataclass(frozen=True)
class ProductMarginRow:
    product_id: uuid.UUID
    name: str
    revenue: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal
    # None when the product has no category set, or the caller didn't
    # supply category_name_by_product — same convention as
    # app/analytics/retail.py's DeadStockEntry.category_name.
    category_name: str | None = None


@dataclass(frozen=True)
class ReturnsSummary:
    """Surfaces what's already netted silently into `RevenueTrend.current`
    — Sale.total_amount already includes negative-quantity return rows
    (app/imports/importer.py's validate_and_parse_row accepts them), so
    net_revenue here is always exactly revenue.current, just explicitly
    decomposed rather than left implicit. A separate dataclass, not a new
    field on RevenueTrend/GrossMarginResult, to avoid any change to their
    existing shape."""

    gross_revenue: Decimal
    returns_amount: Decimal
    return_count: int
    net_revenue: Decimal
    # None when gross_revenue is 0 — nothing to take a percentage of.
    return_rate_pct: Decimal | None


def compute_gross_margin(aggregates: list[ProductPeriodAggregate]) -> GrossMarginResult:
    total_revenue = sum((a.revenue for a in aggregates), Decimal("0"))
    revenue_with_known_cost = sum((a.revenue_with_known_cost for a in aggregates), Decimal("0"))
    cogs = sum((a.cogs for a in aggregates), Decimal("0"))
    gross_profit = revenue_with_known_cost - cogs

    gross_margin_pct = (
        _quantize_pct(gross_profit / revenue_with_known_cost * 100) if revenue_with_known_cost > 0 else None
    )
    cost_data_coverage_pct = _quantize_pct(revenue_with_known_cost / total_revenue * 100) if total_revenue > 0 else None

    revenue_with_known_cost_and_tax = sum((a.revenue_with_known_cost_and_tax for a in aggregates), Decimal("0"))
    tax_amount_known = sum((a.tax_amount_known for a in aggregates), Decimal("0"))
    cogs_for_known_tax = sum((a.cogs_for_known_tax for a in aggregates), Decimal("0"))
    net_revenue_with_known_cost_and_tax = revenue_with_known_cost_and_tax - tax_amount_known
    net_gross_profit = (
        net_revenue_with_known_cost_and_tax - cogs_for_known_tax if revenue_with_known_cost_and_tax > 0 else None
    )
    net_gross_margin_pct = (
        _quantize_pct(net_gross_profit / net_revenue_with_known_cost_and_tax * 100)
        if net_gross_profit is not None and net_revenue_with_known_cost_and_tax > 0
        else None
    )
    tax_data_coverage_pct = (
        _quantize_pct(revenue_with_known_cost_and_tax / revenue_with_known_cost * 100)
        if revenue_with_known_cost > 0
        else None
    )

    return GrossMarginResult(
        total_revenue=_quantize_money(total_revenue),
        revenue_with_known_cost=_quantize_money(revenue_with_known_cost),
        cogs=_quantize_money(cogs),
        gross_profit=_quantize_money(gross_profit),
        gross_margin_pct=gross_margin_pct,
        cost_data_coverage_pct=cost_data_coverage_pct,
        net_gross_profit=_quantize_money(net_gross_profit) if net_gross_profit is not None else None,
        net_gross_margin_pct=net_gross_margin_pct,
        tax_data_coverage_pct=tax_data_coverage_pct,
    )


def compute_revenue_change(current: Decimal, previous: Decimal) -> RevenueTrend:
    change_pct = _quantize_pct((current - previous) / previous * 100) if previous > 0 else None
    return RevenueTrend(current=_quantize_money(current), previous=_quantize_money(previous), change_pct=change_pct)


def compute_returns_summary(net_revenue: Decimal, returns_amount: Decimal, return_count: int) -> ReturnsSummary:
    """net_revenue is Sale.total_amount summed as-is (already includes
    negative-quantity return rows) — gross_revenue is derived from it
    (net + returns), not queried separately, since that's exactly what
    "gross, before returns" means."""
    gross_revenue = net_revenue + returns_amount
    return_rate_pct = _quantize_pct(returns_amount / gross_revenue * 100) if gross_revenue > 0 else None
    return ReturnsSummary(
        gross_revenue=_quantize_money(gross_revenue),
        returns_amount=_quantize_money(returns_amount),
        return_count=return_count,
        net_revenue=_quantize_money(net_revenue),
        return_rate_pct=return_rate_pct,
    )


def rank_products_by_margin(
    aggregates: list[ProductPeriodAggregate],
    products_by_id: dict[uuid.UUID, str],
    *,
    top_n: int = 5,
    category_name_by_product: dict[uuid.UUID, str | None] | None = None,
) -> tuple[list[ProductMarginRow], list[ProductMarginRow], int]:
    """Returns (top_n by gross profit, bottom_n by gross profit, count of
    products excluded for having no known cost). Products with no
    revenue_with_known_cost are excluded from both lists — margin can't be
    ranked for a product with no cost data, and silently ranking it at 0
    would misreport it as break-even rather than unknown.
    """
    category_name_by_product = category_name_by_product or {}
    rows: list[ProductMarginRow] = []
    excluded_count = 0
    for aggregate in aggregates:
        if aggregate.revenue_with_known_cost <= 0:
            excluded_count += 1
            continue
        gross_profit = aggregate.revenue_with_known_cost - aggregate.cogs
        margin_pct = _quantize_pct(gross_profit / aggregate.revenue_with_known_cost * 100)
        name = products_by_id.get(aggregate.product_id, "Unknown product")
        rows.append(
            ProductMarginRow(
                product_id=aggregate.product_id,
                name=name,
                revenue=_quantize_money(aggregate.revenue),
                gross_profit=_quantize_money(gross_profit),
                gross_margin_pct=margin_pct,
                category_name=category_name_by_product.get(aggregate.product_id),
            )
        )

    ranked = sorted(rows, key=lambda row: row.gross_profit, reverse=True)
    top = ranked[:top_n]
    # Bottom N in ascending order (worst first), without re-listing rows
    # already shown in `top` when there are fewer than 2*top_n products.
    bottom_candidates = ranked[len(ranked) - top_n :] if len(ranked) > top_n else []
    bottom = list(reversed(bottom_candidates))
    return top, bottom, excluded_count
