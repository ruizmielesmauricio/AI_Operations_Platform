"""Orchestrates the Retail Operations summary for a route: resolves the
reporting period, pulls raw numbers from the repositories, and feeds them
into the pure formulas in app/analytics/retail.py. No calculation logic of
its own — see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analytics.period import MetricPeriod, resolve_period
from app.analytics.retail import (
    DeadStockEntry,
    InventoryValueResult,
    ProductSalesRow,
    StockCoverRow,
    build_stock_cover_report,
    compute_inventory_value_at_cost,
    compute_sell_through_rate,
    find_dead_stock,
    rank_top_sellers_by_revenue,
    rank_top_sellers_by_units,
)
from app.models.business import Business
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.sale_item import SaleItemRepository

_TOP_N = 5


@dataclass(frozen=True)
class RetailOperationsSummary:
    period: MetricPeriod
    top_sellers_by_units: list[ProductSalesRow]
    top_sellers_by_revenue: list[ProductSalesRow]
    stock_cover: list[StockCoverRow]
    dead_stock: list[DeadStockEntry]
    inventory_value: InventoryValueResult
    # Aggregate sell-through across the whole catalogue for the period.
    # None when there was no stock and no sales at all (nothing to report).
    sell_through_rate: Decimal | None


def get_retail_operations(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    category_id: uuid.UUID | None = None,
) -> RetailOperationsSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, start_date, end_date)

    products = ProductRepository(db).list_for_business(business_id)
    if category_id is not None:
        # Constrains the product set *before* any of the existing
        # formulas run — every downstream calculation (stock cover, dead
        # stock, inventory value, sell-through) is reused completely
        # unmodified, just over a smaller catalogue. A product's own
        # sale/movement rows are never filtered by category directly
        # (there's no category_id on those tables) — only which products
        # are considered at all.
        products = [p for p in products if p.category_id == category_id]
    products_by_id = {product.id: product.name for product in products}
    cost_price_by_product = {product.id: product.cost_price for product in products}
    product_ids = list(products_by_id.keys())

    # Direct request: show each product's category beside its name in
    # every product-row table, independent of whether a filter is active.
    category_name_by_id = {c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business_id)}
    category_name_by_product = {
        product.id: (category_name_by_id.get(product.category_id) if product.category_id else None)
        for product in products
    }

    stock_by_product = InventoryMovementRepository(db).sum_by_product_ids(business_id, product_ids)
    # A product with no movement row yet has 0 stock (per
    # sum_by_product_ids's own convention) — fill in every catalogue
    # product so stock-cover/dead-stock coverage isn't limited to products
    # that happen to have a movement already.
    for product_id in product_ids:
        stock_by_product.setdefault(product_id, 0)

    aggregates = SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    if category_id is not None:
        # aggregate_by_product_in_range has no category filter of its own
        # (it doesn't join Product at all — see its own docstring) and
        # returns every product business-wide; without this, an
        # out-of-category product would still show up in
        # top_sellers_by_units/revenue (falling back to "Unknown product"
        # since it's absent from the already-filtered products_by_id
        # above) and would inflate sell_through_rate's units-sold
        # numerator against an already category-scoped stock denominator.
        aggregates = [a for a in aggregates if a.product_id in products_by_id]
    aggregates_by_product = {a.product_id: a for a in aggregates}

    top_sellers_by_units = rank_top_sellers_by_units(
        aggregates, products_by_id, top_n=_TOP_N, category_name_by_product=category_name_by_product
    )
    top_sellers_by_revenue = rank_top_sellers_by_revenue(
        aggregates, products_by_id, top_n=_TOP_N, category_name_by_product=category_name_by_product
    )
    stock_cover = build_stock_cover_report(
        aggregates_by_product, stock_by_product, products_by_id, period.days,
        category_name_by_product=category_name_by_product,
    )
    dead_stock = find_dead_stock(
        aggregates_by_product, stock_by_product, products_by_id, cost_price_by_product,
        category_name_by_product=category_name_by_product,
    )
    inventory_value = compute_inventory_value_at_cost(stock_by_product, cost_price_by_product)

    total_units_sold = sum(a.units_sold for a in aggregates)
    total_stock_on_hand = sum(stock_by_product.values())
    sell_through_rate = compute_sell_through_rate(total_units_sold, total_stock_on_hand)

    return RetailOperationsSummary(
        period=period,
        top_sellers_by_units=top_sellers_by_units,
        top_sellers_by_revenue=top_sellers_by_revenue,
        stock_cover=stock_cover,
        dead_stock=dead_stock,
        inventory_value=inventory_value,
        sell_through_rate=sell_through_rate,
    )
