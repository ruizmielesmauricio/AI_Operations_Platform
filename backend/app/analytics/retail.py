"""Retail Operations / Inventory Optimization formulas
(02_Operational_Domains.md domain 1, PR-3). Pure — same conventions as
app/analytics/financial.py: plain inputs, quantized Decimal results, no DB,
no I/O. Unit-tested directly in tests/unit/test_retail_analytics.py.
"""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.analytics.types import ProductPeriodAggregate

_CENTS = Decimal("0.01")
_THOUSANDTH = Decimal("0.001")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _quantize_rate(value: Decimal) -> Decimal:
    return value.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)


def compute_stock_cover_days(stock_on_hand: int, units_sold_in_period: int, period_days: int) -> Decimal | None:
    """Days until stock_on_hand runs out at the period's average daily
    sales rate.

    0 if there's no stock at all — it's out of stock now, regardless of how
    fast it was selling. None (not "infinite") if there were zero sales in
    the period despite stock on hand — there's no observed depletion rate
    to project from, so "cover" isn't a knowable number, and returning a
    huge or unbounded value would misreport uncertainty as a fact.
    """
    if stock_on_hand <= 0:
        return Decimal("0")
    if units_sold_in_period <= 0:
        return None
    daily_rate = Decimal(units_sold_in_period) / Decimal(period_days)
    return _quantize_money(Decimal(stock_on_hand) / daily_rate)


def compute_sell_through_rate(units_sold_in_period: int, stock_on_hand: int) -> Decimal | None:
    """units_sold / (units_sold + stock_on_hand), as a 0-1 rate.

    An approximation: there's no beginning-of-period stock snapshot to
    divide into (stock is a derived running total, not a periodic
    snapshot — see InventoryMovement's docstring), so "ending stock plus
    what already sold" stands in for "what was available to sell". None
    when both are 0 (product never had stock or sales at all).
    """
    denominator = units_sold_in_period + stock_on_hand
    if denominator <= 0:
        return None
    return _quantize_rate(Decimal(units_sold_in_period) / Decimal(denominator))


@dataclass(frozen=True)
class DeadStockEntry:
    product_id: uuid.UUID
    name: str
    stock_on_hand: int
    # Cash tied up in this dead stock, at cost — None when the product has
    # no cost_price on record (Stage C10 falls back to ranking by
    # stock_on_hand alone for these, per compute_inventory_value_at_cost's
    # same completeness caveat).
    value_at_cost: Decimal | None


def find_dead_stock(
    aggregates_by_product: dict[uuid.UUID, ProductPeriodAggregate],
    stock_by_product: dict[uuid.UUID, int],
    products_by_id: dict[uuid.UUID, str],
    cost_price_by_product: dict[uuid.UUID, Decimal | None],
) -> list[DeadStockEntry]:
    """Products with stock on hand but zero units sold within the
    requested period. Deliberately uses the same period the rest of the
    report uses rather than an independent fixed lookback window, so the
    whole report stays anchored to one date range — a short requested
    period will over-flag products that simply haven't had a chance to
    sell, which is a caller/UI-level caveat rather than a formula bug.
    """
    entries = []
    for product_id, stock_on_hand in stock_by_product.items():
        if stock_on_hand <= 0:
            continue
        aggregate = aggregates_by_product.get(product_id)
        units_sold = aggregate.units_sold if aggregate is not None else 0
        if units_sold > 0:
            continue
        cost_price = cost_price_by_product.get(product_id)
        value_at_cost = _quantize_money(cost_price * stock_on_hand) if cost_price is not None else None
        entries.append(
            DeadStockEntry(
                product_id=product_id,
                name=products_by_id.get(product_id, "Unknown product"),
                stock_on_hand=stock_on_hand,
                value_at_cost=value_at_cost,
            )
        )
    return sorted(entries, key=lambda entry: entry.stock_on_hand, reverse=True)


@dataclass(frozen=True)
class InventoryValueResult:
    value_at_cost: Decimal
    # Count of products with stock on hand but no cost_price recorded —
    # excluded from value_at_cost, which therefore understates true tied-up
    # cash whenever this is non-zero (PR-3.5 completeness flag).
    products_missing_cost: int


@dataclass(frozen=True)
class ProductSalesRow:
    product_id: uuid.UUID
    name: str
    units_sold: int
    revenue: Decimal


def rank_top_sellers(
    aggregates: list[ProductPeriodAggregate],
    products_by_id: dict[uuid.UUID, str],
    *,
    top_n: int = 5,
) -> list[ProductSalesRow]:
    """Top N products by revenue in the period ("what's selling
    quickly")."""
    rows = [
        ProductSalesRow(
            product_id=a.product_id,
            name=products_by_id.get(a.product_id, "Unknown product"),
            units_sold=a.units_sold,
            revenue=_quantize_money(a.revenue),
        )
        for a in aggregates
    ]
    return sorted(rows, key=lambda row: row.revenue, reverse=True)[:top_n]


@dataclass(frozen=True)
class StockCoverRow:
    product_id: uuid.UUID
    name: str
    stock_on_hand: int
    units_sold_in_period: int
    cover_days: Decimal | None
    # This product's revenue over the same period — how much is actually at
    # stake if it runs out. Lets a caller (e.g. Stage C10's low_stock rule)
    # rank "about to run out" products by what they're worth, not just by
    # how soon they'll run out.
    revenue_in_period: Decimal


def build_stock_cover_report(
    aggregates_by_product: dict[uuid.UUID, ProductPeriodAggregate],
    stock_by_product: dict[uuid.UUID, int],
    products_by_id: dict[uuid.UUID, str],
    period_days: int,
) -> list[StockCoverRow]:
    """One row per product with stock or sales activity, sorted by cover
    ascending (running out soonest first). Rows with unknown cover (no
    recent sales to project a depletion rate from) sort last — "unknown"
    is not "safest" and must not be mixed in with genuinely low-risk rows.
    """
    rows = []
    for product_id, stock_on_hand in stock_by_product.items():
        aggregate = aggregates_by_product.get(product_id)
        units_sold = aggregate.units_sold if aggregate is not None else 0
        revenue_in_period = _quantize_money(aggregate.revenue) if aggregate is not None else Decimal("0.00")
        cover_days = compute_stock_cover_days(stock_on_hand, units_sold, period_days)
        rows.append(
            StockCoverRow(
                product_id=product_id,
                name=products_by_id.get(product_id, "Unknown product"),
                stock_on_hand=stock_on_hand,
                units_sold_in_period=units_sold,
                cover_days=cover_days,
                revenue_in_period=revenue_in_period,
            )
        )
    # Sort key's second element is only ever compared between two rows that
    # both have a real cover_days (first element False == False) — rows
    # with an unknown cover_days (None) always sort after those and never
    # need to be compared against each other, so the placeholder value
    # itself is never used in a real comparison.
    return sorted(
        rows, key=lambda row: (row.cover_days is None, row.cover_days if row.cover_days is not None else Decimal("0"))
    )


def compute_inventory_value_at_cost(
    stock_by_product: dict[uuid.UUID, int],
    cost_price_by_product: dict[uuid.UUID, Decimal | None],
) -> InventoryValueResult:
    total = Decimal("0")
    missing_cost_count = 0
    for product_id, stock_on_hand in stock_by_product.items():
        if stock_on_hand <= 0:
            continue
        cost_price = cost_price_by_product.get(product_id)
        if cost_price is None:
            missing_cost_count += 1
            continue
        total += cost_price * stock_on_hand
    return InventoryValueResult(value_at_cost=_quantize_money(total), products_missing_cost=missing_cost_count)
