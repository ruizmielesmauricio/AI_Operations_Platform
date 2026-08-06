import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.analytics.types import RepairPeriodTotals
from app.models.production_event import ProductionEvent


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

        row = self.session.execute(
            select(
                func.count(ProductionEvent.id),
                func.sum(case((known_price, 1), else_=0)),
                func.sum(case((known_price, ProductionEvent.price_charged), else_=0)),
                func.sum(case((known_both, 1), else_=0)),
                func.sum(case((known_both, ProductionEvent.price_charged), else_=0)),
                func.sum(case((known_both, ProductionEvent.labour_cost), else_=0)),
            ).where(
                ProductionEvent.business_id == business_id,
                ProductionEvent.event_type == "repair",
                ProductionEvent.status == "completed",
                ProductionEvent.completed_at >= start,
                ProductionEvent.completed_at < end,
            )
        ).one()

        repair_count, repairs_with_known_price, revenue, repairs_with_known_both, labour_known_revenue, labour_cost = row
        return RepairPeriodTotals(
            repair_count=int(repair_count or 0),
            repairs_with_known_price=int(repairs_with_known_price or 0),
            revenue=Decimal(revenue or 0),
            repairs_with_known_price_and_labour=int(repairs_with_known_both or 0),
            labour_cost_known_revenue=Decimal(labour_known_revenue or 0),
            labour_cost=Decimal(labour_cost or 0),
        )
