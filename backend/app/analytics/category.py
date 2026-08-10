"""Category Breakdown formulas — revenue, expenses, and stock value per
product category (direct request: a reports table plus a dashboard
filter). Pure — same conventions as app/analytics/financial.py/retail.py:
plain inputs, quantized Decimal results, no DB, no I/O. Unit-tested
directly in tests/unit/test_category_analytics.py.

Three deliberately distinct figures, per the confirmed formulas:
- revenue = sell price x qty sold (SaleItem-based, already computed by
  ProductPeriodAggregate.revenue — reused as-is, not COGS).
- expenses = purchase unit cost x qty received (InventoryMovement-based,
  ProductPurchaseCostAggregate.cost) — NOT cost of goods sold, a
  different, already-existing figure this deliberately doesn't reuse.
- stock_value = current stock on hand x SELL price — deliberately
  different from app/analytics/retail.py's business-wide inventory_value
  stat, which stays at COST price. These are two distinct numbers with
  different meanings, kept separate on purpose.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.analytics.types import ProductPeriodAggregate, ProductPurchaseCostAggregate

_CENTS = Decimal("0.01")
_TENTH_PERCENT = Decimal("0.1")
_UNCATEGORIZED_NAME = "Uncategorized"


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(_TENTH_PERCENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CategoryBreakdownRow:
    # None for the synthetic "Uncategorized" bucket — every product with
    # no category_id (the overwhelming majority until categories are
    # actively imported) lands here rather than being silently dropped.
    category_id: uuid.UUID | None
    category_name: str
    revenue: Decimal
    expenses: Decimal
    # None when this category had zero purchase quantity in the period at
    # all (nothing to have a coverage ratio over) — distinct from 0%,
    # which would mean "purchases happened but none had a known cost."
    expenses_data_coverage_pct: Decimal | None
    stock_value: Decimal
    # Products with stock on hand but no sell_price — excluded from
    # stock_value rather than silently treated as zero (PR-3.5-style
    # completeness disclosure, same precedent as RetailOperationsOut.
    # inventory_value.products_missing_cost).
    products_excluded_from_stock_value: int


def compute_category_breakdown(
    revenue_aggregates: list[ProductPeriodAggregate],
    purchase_aggregates: list[ProductPurchaseCostAggregate],
    stock_on_hand_by_product: dict[uuid.UUID, int],
    category_id_by_product: dict[uuid.UUID, uuid.UUID | None],
    category_name_by_id: dict[uuid.UUID, str],
    sell_price_by_product: dict[uuid.UUID, Decimal | None],
) -> list[CategoryBreakdownRow]:
    """Groups already-fetched per-product data by each product's
    category_id — no SQL join needed (see app/application/
    category_breakdown.py), matching this codebase's established "fetch
    raw, finish in Python" convention (InventoryMovementRepository.
    sum_by_product_ids's own docstring). A product missing from one of
    the three inputs contributes 0 to that figure, not an error — it
    simply had no activity of that kind in the period.

    Every product that appears in ANY of the three inputs is included,
    even one with, say, purchases but no sales this period — a category
    should never silently disappear from the table just because one of
    its three numbers happens to be zero. Sorted by revenue, descending
    (the most commercially significant category first); "Uncategorized"
    is not pinned to either end, it sorts on its own revenue like any
    other row.
    """
    revenue_by_product = {a.product_id: a.revenue for a in revenue_aggregates}
    expenses_by_product = {a.product_id: a.cost for a in purchase_aggregates}
    qty_received_by_product = {a.product_id: a.quantity_received for a in purchase_aggregates}
    qty_known_cost_by_product = {a.product_id: a.quantity_received_with_known_cost for a in purchase_aggregates}

    all_product_ids = set(revenue_by_product) | set(expenses_by_product) | set(stock_on_hand_by_product)

    product_ids_by_category: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    for product_id in all_product_ids:
        product_ids_by_category[category_id_by_product.get(product_id)].append(product_id)

    rows: list[CategoryBreakdownRow] = []
    for category_id, product_ids in product_ids_by_category.items():
        revenue = sum((revenue_by_product.get(pid, Decimal("0")) for pid in product_ids), Decimal("0"))
        expenses = sum((expenses_by_product.get(pid, Decimal("0")) for pid in product_ids), Decimal("0"))

        total_qty_received = sum((qty_received_by_product.get(pid, 0) for pid in product_ids), 0)
        known_qty_received = sum((qty_known_cost_by_product.get(pid, 0) for pid in product_ids), 0)
        coverage_pct = (
            _quantize_pct(Decimal(known_qty_received) / Decimal(total_qty_received) * 100)
            if total_qty_received > 0
            else None
        )

        stock_value = Decimal("0")
        excluded_from_stock_value = 0
        for product_id in product_ids:
            stock = stock_on_hand_by_product.get(product_id, 0)
            if stock <= 0:
                continue
            sell_price = sell_price_by_product.get(product_id)
            if sell_price is None:
                excluded_from_stock_value += 1
                continue
            stock_value += Decimal(stock) * sell_price

        category_name = (
            _UNCATEGORIZED_NAME if category_id is None else category_name_by_id.get(category_id, _UNCATEGORIZED_NAME)
        )
        rows.append(
            CategoryBreakdownRow(
                category_id=category_id,
                category_name=category_name,
                revenue=_quantize_money(revenue),
                expenses=_quantize_money(expenses),
                expenses_data_coverage_pct=coverage_pct,
                stock_value=_quantize_money(stock_value),
                products_excluded_from_stock_value=excluded_from_stock_value,
            )
        )

    rows.sort(key=lambda row: row.revenue, reverse=True)
    return rows
