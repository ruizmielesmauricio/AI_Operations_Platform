"""Orchestrates the dashboard's raw transaction drill-down (Gap 5):
paginated, filtered listings of individual sale line items, purchases,
and repairs behind whatever aggregate row a user clicked through from. No
calculation logic of its own — every field returned is read straight off
the underlying row, nothing is derived or summed here (that's what the
aggregate dashboard sections already do).
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.analytics.period import resolve_period
from app.models.business import Business
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository
from app.repositories.production_event import ProductionEventRepository
from app.repositories.sale_item import SaleItemRepository

# Hard server-side cap — the frontend never needs more than this in one
# page, and this is what actually prevents an unbounded export via direct
# API calls bypassing the UI's own page-size choice (a caller can ask for
# less, never more).
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


@dataclass(frozen=True)
class SaleTransactionRow:
    id: uuid.UUID
    sold_at: object  # datetime
    product_id: uuid.UUID | None
    product_name: str | None
    category_name: str | None
    quantity: int
    unit_price: object  # Decimal
    line_total: object  # Decimal
    order_reference: str | None
    import_record_id: uuid.UUID | None


@dataclass(frozen=True)
class PurchaseTransactionRow:
    id: uuid.UUID
    event_date: date | None
    product_id: uuid.UUID | None
    product_name: str | None
    category_name: str | None
    quantity_delta: int
    unit_cost: object | None  # Decimal
    purchase_reference: str | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    import_record_id: uuid.UUID | None


@dataclass(frozen=True)
class RepairTransactionRow:
    id: uuid.UUID
    completed_at: object  # datetime | None
    description: str | None
    price_charged: object | None  # Decimal
    labour_cost: object | None  # Decimal
    tax_amount: object | None  # Decimal
    repair_reference: str | None
    import_record_id: uuid.UUID | None


@dataclass(frozen=True)
class PaginatedResult:
    items: list
    total: int
    limit: int
    offset: int


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))


def list_sale_transactions(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None,
    end_date: date | None,
    product_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> PaginatedResult:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")
    period = resolve_period(business.timezone, start_date, end_date) if (start_date or end_date) else None

    rows, total = SaleItemRepository(db).list_paginated_for_business(
        business_id,
        start=period.start if period else None,
        end=period.end if period else None,
        product_id=product_id,
        category_id=category_id,
        limit=_clamp_limit(limit),
        offset=max(0, offset),
    )
    category_name_by_id = {c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business_id)}
    items = [
        SaleTransactionRow(
            id=item.id,
            sold_at=sale.sold_at,
            product_id=item.product_id,
            product_name=product.name if product is not None else None,
            category_name=(
                category_name_by_id.get(product.category_id) if product is not None and product.category_id else None
            ),
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.quantity * item.unit_price,
            order_reference=sale.order_reference,
            import_record_id=sale.import_record_id,
        )
        for item, sale, product in rows
    ]
    return PaginatedResult(items=items, total=total, limit=_clamp_limit(limit), offset=max(0, offset))


def list_purchase_transactions(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None,
    end_date: date | None,
    product_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> PaginatedResult:
    rows, total = InventoryMovementRepository(db).list_purchases_paginated(
        business_id,
        start=start_date,
        end=end_date,
        product_id=product_id,
        category_id=category_id,
        limit=_clamp_limit(limit),
        offset=max(0, offset),
    )
    category_name_by_id = {c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business_id)}
    items = [
        PurchaseTransactionRow(
            id=movement.id,
            event_date=movement.event_date,
            product_id=movement.product_id,
            product_name=product.name if product is not None else None,
            category_name=(
                category_name_by_id.get(product.category_id) if product is not None and product.category_id else None
            ),
            quantity_delta=movement.quantity_delta,
            unit_cost=movement.unit_cost,
            purchase_reference=movement.purchase_reference,
            supplier_id=movement.supplier_id,
            supplier_name=supplier.name if supplier is not None else None,
            import_record_id=movement.import_record_id,
        )
        for movement, product, supplier in rows
    ]
    return PaginatedResult(items=items, total=total, limit=_clamp_limit(limit), offset=max(0, offset))


def list_repair_transactions(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None,
    end_date: date | None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> PaginatedResult:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")
    period = resolve_period(business.timezone, start_date, end_date) if (start_date or end_date) else None

    rows, total = ProductionEventRepository(db).list_repairs_paginated(
        business_id,
        start=period.start if period else None,
        end=period.end if period else None,
        limit=_clamp_limit(limit),
        offset=max(0, offset),
    )
    items = [
        RepairTransactionRow(
            id=event.id,
            completed_at=event.completed_at,
            description=event.description,
            price_charged=event.price_charged,
            labour_cost=event.labour_cost,
            tax_amount=event.tax_amount,
            repair_reference=event.repair_reference,
            import_record_id=event.import_record_id,
        )
        for event in rows
    ]
    return PaginatedResult(items=items, total=total, limit=_clamp_limit(limit), offset=max(0, offset))
