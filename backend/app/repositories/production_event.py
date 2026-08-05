import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

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
