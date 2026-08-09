"""Orchestrates the product/threshold management surface (Gap 1 / PR-9.3
follow-up): lists products with their current stock-cover context and a
deterministic recommended low-stock threshold, and applies threshold
edits/accepted recommendations. No calculation logic of its own — see
CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analytics.findings import resolve_low_stock_threshold
from app.analytics.period import resolve_period
from app.analytics.replenishment import ThresholdRecommendation, recommend_low_stock_threshold
from app.analytics.retail import build_stock_cover_report
from app.models.business import Business
from app.repositories.audit_log import record_audit_event
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.sale_item import SaleItemRepository
from app.repositories.supplier import SupplierRepository

# Products/threshold recommendations look back a fixed 30 days, independent
# of any dashboard date filter — this is a management view of "how is this
# product doing generally," not a period report, so it deliberately never
# takes start/end params the way analytics routes do.
_LOOKBACK_DAYS = 30


class ProductNotFound(Exception):
    pass


class CategoryNotFound(Exception):
    pass


@dataclass(frozen=True)
class ProductThresholdRow:
    product_id: uuid.UUID
    name: str
    sku: str | None
    category_id: uuid.UUID | None
    category_name: str | None
    stock_on_hand: int
    units_sold_in_period: int
    cover_days: Decimal | None
    # The value actually in effect right now (product override, else
    # category override, else the global default) — what evaluate_low_stock
    # actually alerts against today.
    effective_threshold_days: Decimal
    # Only set when *this product* has an explicit override — None means
    # it's currently inheriting from its category or the default, which
    # the UI shows distinctly from "explicitly set to the default value."
    product_threshold_days: Decimal | None
    recommendation: ThresholdRecommendation
    # Not enough sales history to say anything meaningful about how this
    # product sells yet — the UI shows this instead of a recommendation
    # it can't really back up with real velocity data.
    insufficient_data: bool


def list_product_thresholds(
    db: Session, *, business_id: uuid.UUID, category_id: uuid.UUID | None = None
) -> list[ProductThresholdRow]:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, None, None, default_window_days=_LOOKBACK_DAYS)

    product_repo = ProductRepository(db)
    products = product_repo.list_for_business(business_id)
    if category_id is not None:
        products = [p for p in products if p.category_id == category_id]
    products_by_id = {p.id: p.name for p in products}
    product_ids = list(products_by_id.keys())

    categories_by_id = {c.id: c for c in ProductCategoryRepository(db).list_for_business(business_id)}
    category_name_by_product = {
        p.id: (categories_by_id[p.category_id].name if p.category_id in categories_by_id else None) for p in products
    }

    stock_by_product = InventoryMovementRepository(db).sum_by_product_ids(business_id, product_ids)
    for product_id in product_ids:
        stock_by_product.setdefault(product_id, 0)

    aggregates = {
        a.product_id: a
        for a in SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    }
    stock_cover_rows = build_stock_cover_report(
        aggregates, stock_by_product, products_by_id, period.days, category_name_by_product
    )
    cover_by_product = {r.product_id: r for r in stock_cover_rows}

    supplier_repo = SupplierRepository(db)

    rows: list[ProductThresholdRow] = []
    for product in products:
        cover_row = cover_by_product.get(product.id)
        units_sold = cover_row.units_sold_in_period if cover_row is not None else 0
        cover_days = cover_row.cover_days if cover_row is not None else None
        category = categories_by_id.get(product.category_id) if product.category_id else None

        effective = resolve_low_stock_threshold(
            product.low_stock_threshold_days, category.low_stock_threshold_days if category is not None else None
        )
        lead_time_days = supplier_repo.preferred_lead_time_days(business_id, product.id)
        recommendation = recommend_low_stock_threshold(
            lead_time_days=lead_time_days, current_threshold_days=effective
        )

        rows.append(
            ProductThresholdRow(
                product_id=product.id,
                name=product.name,
                sku=product.sku,
                category_id=product.category_id,
                category_name=category_name_by_product.get(product.id),
                stock_on_hand=stock_by_product.get(product.id, 0),
                units_sold_in_period=units_sold,
                cover_days=cover_days,
                effective_threshold_days=effective,
                product_threshold_days=product.low_stock_threshold_days,
                recommendation=recommendation,
                insufficient_data=units_sold == 0,
            )
        )
    rows.sort(key=lambda r: r.name)
    return rows


def update_product_threshold(
    db: Session,
    *,
    business_id: uuid.UUID,
    product_id: uuid.UUID,
    threshold_days: Decimal | None,
    editing_user_id: str,
    accepted_recommendation: bool = False,
) -> None:
    product = ProductRepository(db).update_low_stock_threshold_days(
        business_id=business_id, product_id=product_id, threshold_days=threshold_days
    )
    if product is None:
        raise ProductNotFound(str(product_id))
    action = "threshold_recommendation_accepted" if accepted_recommendation else "threshold_updated"
    record_audit_event(
        db, business_id=business_id, user_id=editing_user_id, action=action,
        target_type="product", target_id=str(product_id),
        metadata={"threshold_days": str(threshold_days) if threshold_days is not None else None},
    )
    db.commit()


def update_category_threshold(
    db: Session, *, business_id: uuid.UUID, category_id: uuid.UUID, threshold_days: Decimal | None, editing_user_id: str
) -> None:
    category = ProductCategoryRepository(db).update_low_stock_threshold_days(
        business_id=business_id, category_id=category_id, threshold_days=threshold_days
    )
    if category is None:
        raise CategoryNotFound(str(category_id))
    record_audit_event(
        db, business_id=business_id, user_id=editing_user_id, action="threshold_updated",
        target_type="product_category", target_id=str(category_id),
        metadata={"threshold_days": str(threshold_days) if threshold_days is not None else None},
    )
    db.commit()
