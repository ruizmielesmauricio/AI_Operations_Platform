import uuid
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.sale import SaleItem


class SaleItemRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        sale_id: uuid.UUID,
        product_id: uuid.UUID | None,
        quantity: int,
        unit_price: Decimal,
        cost_price_at_sale: Decimal | None,
    ) -> SaleItem:
        # Flush only — app/imports/importer.py owns the single commit.
        item = SaleItem(
            business_id=business_id,
            sale_id=sale_id,
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
            cost_price_at_sale=cost_price_at_sale,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def list_ids_by_sale_ids(self, sale_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if not sale_ids:
            return []
        return list(self.session.scalars(select(SaleItem.id).where(SaleItem.sale_id.in_(sale_ids))))

    def bulk_delete_by_sale_ids(self, sale_ids: list[uuid.UUID]) -> None:
        if not sale_ids:
            return
        self.session.execute(delete(SaleItem).where(SaleItem.sale_id.in_(sale_ids)))
        self.session.flush()
