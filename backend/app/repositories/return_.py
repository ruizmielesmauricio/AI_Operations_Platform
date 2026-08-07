import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.return_ import Return
from app.models.sale import Sale, SaleItem


class ReturnRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        sale_item_id: uuid.UUID,
        refund_amount: Decimal | None,
        reason: str | None = None,
    ) -> Return:
        # Flush only — app/imports/importer.py owns the single commit.
        # reason is left None by the importer: the source file gives no
        # "why" data, and this platform never invents one.
        row = Return(
            business_id=business_id, sale_item_id=sale_item_id, refund_amount=refund_amount, reason=reason,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def sum_refund_amount_in_range(self, business_id: uuid.UUID, start: datetime, end: datetime) -> Decimal:
        """Total refunded in [start, end) — mirrors SaleRepository.
        sum_total_amount_in_range's exact shape. Joined through SaleItem
        -> Sale to filter by the sale's own date, since Return itself
        carries no date of its own (a return is dated by the sale line it
        reverses, not a separate event)."""
        total = self.session.scalar(
            select(func.coalesce(func.sum(Return.refund_amount), 0))
            .join(SaleItem, SaleItem.id == Return.sale_item_id)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(Return.business_id == business_id, Sale.sold_at >= start, Sale.sold_at < end)
        )
        return Decimal(total)

    def count_in_range(self, business_id: uuid.UUID, start: datetime, end: datetime) -> int:
        total = self.session.scalar(
            select(func.count(Return.id))
            .join(SaleItem, SaleItem.id == Return.sale_item_id)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(Return.business_id == business_id, Sale.sold_at >= start, Sale.sold_at < end)
        )
        return int(total or 0)
