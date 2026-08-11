"""Orchestrates the weekly consolidated stock review (ORLA Notifications/
Security/Retention prompt, section 2): pulls the exact same building
blocks Retail Operations (app/application/retail_operations.py) and
Product Reorder Rules (app/application/products.py) already compute for
this business, classifies them via app/analytics/stock_review.py, and
hands the counts to app/application/notifications.py::notify_stock_
review. No calculation logic of its own — see CLAUDE.md's "Business
Logic First".
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.analytics.findings import resolve_low_stock_threshold
from app.analytics.period import resolve_period
from app.analytics.retail import build_stock_cover_report, find_dead_stock
from app.analytics.stock_review import StockReviewSummary, classify_stock_review
from app.models.business import Business
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.sale_item import SaleItemRepository

# Matches app/application/products.py's own _LOOKBACK_DAYS — "how is this
# product doing generally," not a period report, so it uses the same
# fixed 30-day window that already backs the Product Reorder Rules page's
# own stale/velocity judgment, rather than a second, different number.
_LOOKBACK_DAYS = 30


def get_stock_review(db: Session, *, business_id: uuid.UUID, now: datetime | None = None) -> StockReviewSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, None, None, default_window_days=_LOOKBACK_DAYS, now=now)

    products = ProductRepository(db).list_for_business(business_id)
    products_by_id = {p.id: p.name for p in products}
    product_ids = list(products_by_id.keys())
    cost_price_by_product = {p.id: p.cost_price for p in products}

    stock_by_product = InventoryMovementRepository(db).sum_by_product_ids(business_id, product_ids)
    for product_id in product_ids:
        stock_by_product.setdefault(product_id, 0)

    aggregates = {
        a.product_id: a
        for a in SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    }
    stock_cover_rows = build_stock_cover_report(aggregates, stock_by_product, products_by_id, period.days)
    dead_stock_entries = find_dead_stock(aggregates, stock_by_product, products_by_id, cost_price_by_product)

    categories_by_id = {c.id: c for c in ProductCategoryRepository(db).list_for_business(business_id)}
    effective_threshold_by_product = {
        product.id: resolve_low_stock_threshold(
            product.low_stock_threshold_days,
            categories_by_id[product.category_id].low_stock_threshold_days
            if product.category_id in categories_by_id
            else None,
        )
        for product in products
    }

    return classify_stock_review(stock_by_product, stock_cover_rows, dead_stock_entries, effective_threshold_by_product)
