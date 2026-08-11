import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.analytics.types import RepairPeriodTotals
from app.models.production_event import ProductionEvent

_SEARCH_LIMIT = 5


class ProductionEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        event_type: str,
        description: str | None,
        status: str,
        opened_at: datetime,
        completed_at: datetime | None,
        labour_cost: Decimal | None,
        price_charged: Decimal | None,
        customer_id: uuid.UUID | None,
        performed_by_id: uuid.UUID | None,
        import_record_id: uuid.UUID | None,
        repair_reference: str | None = None,
        tax_amount: Decimal | None = None,
    ) -> ProductionEvent:
        # Flush only — app/imports/importer.py owns the single commit.
        event = ProductionEvent(
            business_id=business_id,
            event_type=event_type,
            description=description,
            status=status,
            opened_at=opened_at,
            completed_at=completed_at,
            labour_cost=labour_cost,
            price_charged=price_charged,
            customer_id=customer_id,
            performed_by_id=performed_by_id,
            import_record_id=import_record_id,
            repair_reference=repair_reference,
            tax_amount=tax_amount,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_ids_by_import_record(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            self.session.scalars(
                select(ProductionEvent.id).where(
                    ProductionEvent.business_id == business_id,
                    ProductionEvent.import_record_id == import_record_id,
                )
            )
        )

    def bulk_delete_by_ids(self, event_ids: list[uuid.UUID]) -> None:
        if not event_ids:
            return
        self.session.execute(delete(ProductionEvent).where(ProductionEvent.id.in_(event_ids)))
        self.session.flush()

    def list_existing_repair_reference_signatures(
        self, business_id: uuid.UUID
    ) -> set[tuple[str, str | None, Decimal | None, Decimal | None]]:
        """Every non-null (repair_reference, description, price_charged,
        labour_cost) tuple already used by this business's repairs, across
        all prior imports — one query, not N+1. Used to reject a
        re-uploaded/overlapping repairs file per row instead of silently
        double-counting workshop revenue (app/imports/importer.py::_write_repairs).

        Keyed by more than just the reference — repairs have no product_id
        the way purchases do, but one invoice/job number can still cover
        several repairs (e.g. two bikes serviced on one ticket), so the
        rest of the row's own detail is folded in as the next-best
        disambiguator; two genuinely different repairs sharing one
        reference will very rarely also share every other field."""
        rows = self.session.execute(
            select(
                ProductionEvent.repair_reference,
                ProductionEvent.description,
                ProductionEvent.price_charged,
                ProductionEvent.labour_cost,
            ).where(
                ProductionEvent.business_id == business_id,
                ProductionEvent.event_type == "repair",
                ProductionEvent.repair_reference.isnot(None),
            )
        ).all()
        return {(ref, description, price_charged, labour_cost) for ref, description, price_charged, labour_cost in rows}

    def search_repairs(
        self, business_id: uuid.UUID, query: str, *, limit: int = _SEARCH_LIMIT
    ) -> list[ProductionEvent]:
        """Backs the global search bar's "repairs" group — OR across
        repair_reference and description, unlike find_repairs below
        (ORLA chat lookup), which ANDs whichever single filter the
        classifier named. No customer PII: customer_id is never selected
        here, and description is free text from the shop's own repair
        log, not a customer record."""
        needle = f"%{query.strip()}%"
        return list(
            self.session.scalars(
                select(ProductionEvent)
                .where(
                    ProductionEvent.business_id == business_id,
                    ProductionEvent.event_type == "repair",
                    or_(
                        ProductionEvent.repair_reference.ilike(needle),
                        ProductionEvent.description.ilike(needle),
                    ),
                )
                .order_by(ProductionEvent.completed_at.desc(), ProductionEvent.id.desc())
                .limit(limit)
            )
        )

    def find_repairs(
        self,
        business_id: uuid.UUID,
        *,
        repair_reference: str | None = None,
        description_contains: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 10,
    ) -> list[ProductionEvent]:
        """Backs ORLA's repair_lookup chat intent ("how much did repair
        JOB-364 cost" / "what repairs did I do last week") — event_type
        is always fixed to "repair" here, unlike this repository's other
        read paths, which are business-wide across both event types; a
        lookup should never accidentally surface a production batch.
        Tries `repair_reference` first (case-insensitive substring, same
        reasoning as InventoryMovementRepository.list_purchases's
        purchase_reference match); `description_contains` is a fallback
        for when no reference was named — repairs have no product_id or
        reliable customer name to search by instead
        (ProductionEvent.customer_id is NULL on every imported repair, no
        match key from free text in a file). Most-recent-first by
        opened_at, capped at `limit` for the same reason every other new
        lookup method in this pass is capped.
        """
        conditions = [ProductionEvent.business_id == business_id, ProductionEvent.event_type == "repair"]
        if repair_reference is not None:
            needle = repair_reference.strip().upper()
            conditions.append(func.upper(ProductionEvent.repair_reference).like(f"%{needle}%"))
        if description_contains is not None:
            needle = description_contains.strip().lower()
            conditions.append(func.lower(ProductionEvent.description).like(f"%{needle}%"))
        if start is not None:
            conditions.append(ProductionEvent.opened_at >= start)
        if end is not None:
            conditions.append(ProductionEvent.opened_at < end)
        return list(
            self.session.scalars(
                select(ProductionEvent).where(*conditions).order_by(ProductionEvent.opened_at.desc()).limit(limit)
            )
        )

    def aggregate_completed_repairs_in_range(
        self, business_id: uuid.UUID, start: datetime, end: datetime
    ) -> RepairPeriodTotals:
        """One query, business-wide (no group_by — a repair has no product
        to break down by). completed_at is the filter field: the repairs
        importer sets it equal to opened_at (a periodic export has no
        separate "opened" timestamp to offer), so it's the one reliable
        date on a completed repair, mirroring Sale.sold_at's role."""
        known_price = ProductionEvent.price_charged.isnot(None)
        known_both = known_price & ProductionEvent.labour_cost.isnot(None)
        known_both_and_tax = known_both & ProductionEvent.tax_amount.isnot(None)

        row = self.session.execute(
            select(
                func.count(ProductionEvent.id),
                func.sum(case((known_price, 1), else_=0)),
                func.sum(case((known_price, ProductionEvent.price_charged), else_=0)),
                func.sum(case((known_both, 1), else_=0)),
                func.sum(case((known_both, ProductionEvent.price_charged), else_=0)),
                func.sum(case((known_both, ProductionEvent.labour_cost), else_=0)),
                func.sum(case((known_both_and_tax, ProductionEvent.price_charged), else_=0)),
                func.sum(case((known_both_and_tax, ProductionEvent.tax_amount), else_=0)),
                func.sum(case((known_both_and_tax, ProductionEvent.labour_cost), else_=0)),
            ).where(
                ProductionEvent.business_id == business_id,
                ProductionEvent.event_type == "repair",
                ProductionEvent.status == "completed",
                ProductionEvent.completed_at >= start,
                ProductionEvent.completed_at < end,
            )
        ).one()

        (
            repair_count,
            repairs_with_known_price,
            revenue,
            repairs_with_known_both,
            labour_known_revenue,
            labour_cost,
            labour_known_revenue_with_known_tax,
            tax_amount_known,
            labour_cost_for_known_tax,
        ) = row
        return RepairPeriodTotals(
            repair_count=int(repair_count or 0),
            repairs_with_known_price=int(repairs_with_known_price or 0),
            revenue=Decimal(revenue or 0),
            repairs_with_known_price_and_labour=int(repairs_with_known_both or 0),
            labour_cost_known_revenue=Decimal(labour_known_revenue or 0),
            labour_cost=Decimal(labour_cost or 0),
            labour_cost_known_revenue_with_known_tax=Decimal(labour_known_revenue_with_known_tax or 0),
            tax_amount_known=Decimal(tax_amount_known or 0),
            labour_cost_for_known_tax=Decimal(labour_cost_for_known_tax or 0),
        )

    def list_repairs_paginated(
        self,
        business_id: uuid.UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[ProductionEvent], int]:
        """Real pagination behind the dashboard's transaction drill-down
        (Gap 5) — deliberately separate from find_repairs above (ORLA
        chat lookup, fixed low limit, reference/description search, no
        offset). No category filter: a repair has no product_id to hang
        one off (see ProductionEvent's own docstring). Most-recent-first,
        stable (completed_at, id) ordering.
        """
        conditions = [ProductionEvent.business_id == business_id, ProductionEvent.event_type == "repair"]
        if start is not None:
            conditions.append(ProductionEvent.completed_at >= start)
        if end is not None:
            conditions.append(ProductionEvent.completed_at < end)

        total = self.session.scalar(select(func.count()).select_from(ProductionEvent).where(*conditions)) or 0
        rows = list(
            self.session.scalars(
                select(ProductionEvent)
                .where(*conditions)
                .order_by(ProductionEvent.completed_at.desc(), ProductionEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        return rows, total
