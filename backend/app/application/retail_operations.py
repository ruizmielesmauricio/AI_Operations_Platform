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
from app.repositories.product import ProductRepository
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
) -> RetailOperationsSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, start_date, end_date)

    products = ProductRepository(db).list_for_business(business_id)
    products_by_id = {product.id: product.name for product in products}
    cost_price_by_product = {product.id: product.cost_price for product in products}
    product_ids = list(products_by_id.keys())

    stock_by_product = InventoryMovementRepository(db).sum_by_product_ids(business_id, product_ids)
    # A product with no movement row yet has 0 stock (per
    # sum_by_product_ids's own convention) — fill in every catalogue
    # product so stock-cover/dead-stock coverage isn't limited to products
    # that happen to have a movement already.
    for product_id in product_ids:
        stock_by_product.setdefault(product_id, 0)

    aggregates = SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    aggregates_by_product = {a.product_id: a for a in aggregates}

    top_sellers_by_units = rank_top_sellers_by_units(aggregates, products_by_id, top_n=_TOP_N)
    top_sellers_by_revenue = rank_top_sellers_by_revenue(aggregates, products_by_id, top_n=_TOP_N)
    stock_cover = build_stock_cover_report(aggregates_by_product, stock_by_product, products_by_id, period.days)
    dead_stock = find_dead_stock(aggregates_by_product, stock_by_product, products_by_id, cost_price_by_product)
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
