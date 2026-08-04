import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.sale import Sale


class SaleRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        sold_at: datetime,
        total_amount: Decimal,
        order_reference: str | None,
        import_record_id: uuid.UUID,
        customer_id: uuid.UUID | None = None,
    ) -> Sale:
        # Flush only — app/imports/importer.py owns the single commit.
        sale = Sale(
            business_id=business_id,
            sold_at=sold_at,
            total_amount=total_amount,
            order_reference=order_reference,
            import_record_id=import_record_id,
            customer_id=customer_id,
        )
        self.session.add(sale)
        self.session.flush()
        return sale

    def list_ids_by_import_record(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            self.session.scalars(
                select(Sale.id).where(
                    Sale.business_id == business_id, Sale.import_record_id == import_record_id
                )
            )
        )

    def bulk_delete_by_ids(self, sale_ids: list[uuid.UUID]) -> None:
        if not sale_ids:
            return
        self.session.execute(delete(Sale).where(Sale.id.in_(sale_ids)))
        self.session.flush()
