"""Global search bar (Notification Centre + search batch): one free-text
query, tenant-scoped to a single business/branch, grouped by result type.
No calculation logic of its own — every field returned is read straight
off the underlying row through the same repositories the rest of the app
already uses (ProductRepository.search_by_name_or_sku already exists,
built for ORLA chat; the others are new, narrower siblings of methods
that already existed for chat/transactions, added because those have
different — AND, not OR — filter semantics a search bar doesn't want).
Every query is parameterized ILIKE through SQLAlchemy, never raw SQL
string interpolation.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.business import Business
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.production_event import ProductionEventRepository
from app.repositories.sale_item import SaleItemRepository
from app.repositories.supplier import SupplierRepository
from app.schemas.search import (
    ProductSearchResultOut,
    PurchaseSearchResultOut,
    RepairSearchResultOut,
    SaleSearchResultOut,
    SearchResultOut,
    SupplierSearchResultOut,
)

# Below this, a query is almost always the start of a word still being
# typed — running it would just churn the database for results the user
# hasn't finished asking for yet. Returning an empty result here (not a
# 422) matches "reject or return empty for very short queries" — a
# search box shouldn't ever show a scary error just because someone's
# only typed one character so far.
MIN_QUERY_LENGTH = 2
# Per-group cap — matches ProductRepository.search_by_name_or_sku's own
# existing default (built for ORLA chat) rather than inventing a second
# number. The API layer clamps whatever a caller asks for to this range.
DEFAULT_LIMIT_PER_GROUP = 5
MAX_LIMIT_PER_GROUP = 20


def global_search(db: Session, *, business_id: uuid.UUID, query: str, limit: int = DEFAULT_LIMIT_PER_GROUP) -> SearchResultOut:
    stripped = query.strip()
    empty = SearchResultOut(query=stripped, products=[], sales=[], purchases=[], suppliers=[], repairs=[])
    if len(stripped) < MIN_QUERY_LENGTH:
        return empty

    business = db.get(Business, business_id)
    if business is None:
        return empty

    clamped_limit = max(1, min(limit, MAX_LIMIT_PER_GROUP))

    products = ProductRepository(db).search_by_name_or_sku(business_id, stripped, limit=clamped_limit)
    category_name_by_id = {c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business_id)}
    stock_by_product_id = InventoryMovementRepository(db).sum_by_product_ids(business_id, [p.id for p in products])
    product_results = [
        ProductSearchResultOut(
            id=p.id,
            name=p.name,
            sku=p.sku,
            category_name=category_name_by_id.get(p.category_id) if p.category_id else None,
            current_stock=stock_by_product_id.get(p.id),
        )
        for p in products
    ]

    sale_rows = SaleItemRepository(db).search_sales(business_id, stripped, limit=clamped_limit)
    sale_results = [
        SaleSearchResultOut(
            id=item.id,
            sold_at=sale.sold_at,
            product_id=item.product_id,
            product_name=product.name if product is not None else None,
            sku=product.sku if product is not None else None,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.quantity * item.unit_price,
            order_reference=sale.order_reference,
        )
        for item, sale, product in sale_rows
    ]

    purchase_rows = InventoryMovementRepository(db).search_purchases(business_id, stripped, limit=clamped_limit)
    purchase_results = [
        PurchaseSearchResultOut(
            id=movement.id,
            event_date=movement.event_date,
            product_id=movement.product_id,
            product_name=product.name if product is not None else None,
            sku=product.sku if product is not None else None,
            supplier_name=supplier.name if supplier is not None else None,
            quantity_delta=movement.quantity_delta,
            purchase_reference=movement.purchase_reference,
        )
        for movement, product, supplier in purchase_rows
    ]

    suppliers = SupplierRepository(db).search_by_name(business_id, stripped, limit=clamped_limit)
    supplier_results = [
        SupplierSearchResultOut(id=s.id, name=s.name, contact_info=s.contact_info, status=s.status) for s in suppliers
    ]

    # Repairs only exist as a concept for templates that actually track
    # them (bicycle_shop today) — same gate app/application/report.py
    # already uses for Workshop Performance, reused here rather than
    # invented fresh, so a coffee-shop-template business never sees an
    # empty "Repairs" group implying a feature it doesn't have.
    repair_results: list[RepairSearchResultOut] = []
    if business.template == "bicycle_shop":
        repairs = ProductionEventRepository(db).search_repairs(business_id, stripped, limit=clamped_limit)
        repair_results = [
            RepairSearchResultOut(
                id=r.id,
                completed_at=r.completed_at,
                description=r.description,
                repair_reference=r.repair_reference,
                price_charged=r.price_charged,
            )
            for r in repairs
        ]

    return SearchResultOut(
        query=stripped,
        products=product_results,
        sales=sale_results,
        purchases=purchase_results,
        suppliers=supplier_results,
        repairs=repair_results,
    )
