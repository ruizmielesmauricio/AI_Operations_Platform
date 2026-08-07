"""Orchestrates the Category Breakdown summary (revenue/expenses/stock
value per product category) for a route: resolves the reporting period,
pulls raw numbers from the repositories, and feeds them into the pure
grouping in app/analytics/category.py. No calculation logic of its own —
see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.analytics.category import CategoryBreakdownRow, compute_category_breakdown
from app.analytics.period import MetricPeriod, resolve_period
from app.models.business import Business
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.sale_item import SaleItemRepository


@dataclass(frozen=True)
class CategoryBreakdownSummary:
    period: MetricPeriod
    rows: list[CategoryBreakdownRow]


def get_category_breakdown(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> CategoryBreakdownSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, start_date, end_date)

    # InventoryMovement.event_date is a plain business-local calendar date
    # (not a UTC timestamp) — recovered from the resolved UTC period by
    # converting back through the business's own timezone, the exact
    # inverse of what resolve_period itself does. period.end is the
    # exclusive UTC boundary (midnight of the day *after* the last
    # included local day per MetricPeriod's own half-open convention), so
    # one day is subtracted after converting back to recover the last
    # *inclusive* local date — matching InventoryMovementRepository.
    # list_purchases's existing inclusive start/end convention.
    tz = ZoneInfo(business.timezone)
    local_start = period.start.astimezone(tz).date()
    local_end = (period.end.astimezone(tz) - timedelta(days=1)).date()

    products = ProductRepository(db).list_for_business(business_id)
    categories = ProductCategoryRepository(db).list_for_business(business_id)
    category_name_by_id = {c.id: c.name for c in categories}
    category_id_by_product = {p.id: p.category_id for p in products}
    sell_price_by_product = {p.id: p.sell_price for p in products}
    all_product_ids = [p.id for p in products]

    revenue_aggregates = SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    purchase_aggregates = InventoryMovementRepository(db).aggregate_purchase_cost_by_product_in_range(
        business_id, local_start, local_end
    )
    stock_on_hand_by_product = InventoryMovementRepository(db).sum_by_product_ids(business_id, all_product_ids)

    rows = compute_category_breakdown(
        revenue_aggregates,
        purchase_aggregates,
        stock_on_hand_by_product,
        category_id_by_product,
        category_name_by_id,
        sell_price_by_product,
    )

    return CategoryBreakdownSummary(period=period, rows=rows)
