"""Orchestrates ORLA's per-record lookup intents (product_lookup/
purchase_lookup/repair_lookup, app/ai/service.py) — resolves a free-text
search term (extracted by the classify step, never trusted for anything
beyond a parameterized repository query) against the matching
repository, and returns every match found so the caller can apply the
shared 0/1/many disambiguation rule (app/ai/service.py::_dispatch_lookup).
No calculation logic of its own — see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.analytics.period import resolve_period
from app.models.inventory_movement import InventoryMovement
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductRepository
from app.repositories.production_event import ProductionEventRepository
from app.schemas.analytics import ProductDetailOut, PurchaseDetailOut, RepairDetailOut


@dataclass(frozen=True)
class LookupResult:
    # Each already JSON-serializable (model_dump(mode="json")) — ready to
    # hand straight to the AI explain call as context, same as every
    # other intent's fetched data.
    matches: list[dict] = field(default_factory=list)
    # Short human labels, one per match, used only for the deterministic
    # "found several matching X — which one?" disambiguation message
    # (app/ai/service.py) — never shown as the final answer itself.
    match_labels: list[str] = field(default_factory=list)


def find_products(db: Session, *, business_id: uuid.UUID, query: str) -> LookupResult:
    products = ProductRepository(db).search_by_name_or_sku(business_id, query)
    if not products:
        return LookupResult()

    stock_by_id = InventoryMovementRepository(db).sum_by_product_ids(business_id, [p.id for p in products])
    matches = [
        ProductDetailOut(
            product_id=p.id,
            name=p.name,
            sku=p.sku,
            cost_price=p.cost_price,
            sell_price=p.sell_price,
            current_stock=stock_by_id.get(p.id, 0),
        ).model_dump(mode="json")
        for p in products
    ]
    labels = [f"{p.name}" + (f" ({p.sku})" if p.sku else "") for p in products]
    return LookupResult(matches=matches, match_labels=labels)


def find_purchases(
    db: Session,
    *,
    business_id: uuid.UUID,
    search_term: str | None,
    start_date: date | None,
    end_date: date | None,
) -> LookupResult:
    movement_repo = InventoryMovementRepository(db)
    product_id: uuid.UUID | None = None

    if search_term:
        # Try the term as a purchase/PO reference first.
        by_reference = movement_repo.list_purchases(
            business_id, purchase_reference=search_term, start=start_date, end=end_date
        )
        if by_reference:
            return _purchases_to_result(db, business_id, by_reference)

        # No reference match — try resolving it as a product instead.
        # Multiple product matches is itself the ambiguity to surface
        # (which product did they mean), not something to guess past.
        products = ProductRepository(db).search_by_name_or_sku(business_id, search_term)
        if len(products) > 1:
            labels = [f"{p.name}" + (f" ({p.sku})" if p.sku else "") for p in products]
            return LookupResult(match_labels=labels)
        if len(products) == 1:
            product_id = products[0].id
        # Zero product matches either — fall through to a plain
        # date-range search below (still useful if a date was given;
        # otherwise correctly comes back empty).

    movements = movement_repo.list_purchases(business_id, product_id=product_id, start=start_date, end=end_date)
    return _purchases_to_result(db, business_id, movements)


def _purchases_to_result(db: Session, business_id: uuid.UUID, movements: list[InventoryMovement]) -> LookupResult:
    if not movements:
        return LookupResult()
    # Same "load the whole catalogue once" pattern already used by
    # app/application/financial_performance.py for the same reason — a
    # handful of id->name lookups doesn't justify a per-row query.
    products_by_id = {p.id: p for p in ProductRepository(db).list_for_business(business_id)}

    matches = []
    labels = []
    for movement in movements:
        product = products_by_id.get(movement.product_id)
        name = product.name if product else "Unknown product"
        matches.append(
            PurchaseDetailOut(
                product_id=movement.product_id,
                product_name=name,
                sku=product.sku if product else None,
                quantity_received=movement.quantity_delta,
                purchase_reference=movement.purchase_reference,
                event_date=movement.event_date,
                unit_cost=movement.unit_cost,
            ).model_dump(mode="json")
        )
        labels.append(f"{name}, {movement.event_date} ({movement.purchase_reference or 'no reference'})")
    return LookupResult(matches=matches, match_labels=labels)


def find_repairs(
    db: Session,
    *,
    business_id: uuid.UUID,
    business_timezone: str,
    search_term: str | None,
    start_date: date | None,
    end_date: date | None,
) -> LookupResult:
    repo = ProductionEventRepository(db)

    # opened_at/completed_at are real datetimes (unlike a purchase's
    # plain event_date) — reuse the same business-timezone-aware
    # resolution every other intent's date range already goes through,
    # rather than re-deriving UTC boundaries by hand. Only resolved when
    # a date was actually given — resolve_period defaults to "last 30
    # days" when both are None, which is not what an unfiltered repair
    # search should mean.
    start_dt = end_dt = None
    if start_date is not None or end_date is not None:
        period = resolve_period(business_timezone, start_date, end_date)
        start_dt, end_dt = period.start, period.end

    events = []
    if search_term:
        events = repo.find_repairs(business_id, repair_reference=search_term, start=start_dt, end=end_dt)
        if not events:
            events = repo.find_repairs(business_id, description_contains=search_term, start=start_dt, end=end_dt)
    else:
        events = repo.find_repairs(business_id, start=start_dt, end=end_dt)

    if not events:
        return LookupResult()

    matches = [
        RepairDetailOut(
            repair_reference=event.repair_reference,
            description=event.description,
            status=event.status,
            opened_at=event.opened_at,
            completed_at=event.completed_at,
            price_charged=event.price_charged,
            labour_cost=event.labour_cost,
        ).model_dump(mode="json")
        for event in events
    ]
    labels = [
        f"{event.repair_reference or 'no reference'} — {event.description or 'no description'}" for event in events
    ]
    return LookupResult(matches=matches, match_labels=labels)
