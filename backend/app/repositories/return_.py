import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
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

    def bulk_delete_by_sale_item_ids(self, sale_item_ids: list[uuid.UUID]) -> None:
        """Undo-ordering audit finding: `_undo_sales_import`
        (app/imports/importer.py) bulk-deletes `SaleItem` rows directly,
        but `Return.sale_item_id` has no `ondelete="CASCADE"` — deleting a
        sale item that still has a Return pointing at it violates that FK
        in Postgres (returns_sale_item_id_fkey), confirmed live: undoing
        any sales import that included even one return crashed outright.
        SQLite (the integration test suite's own engine) doesn't enforce
        FKs by default, so this was invisible there — the exact same
        "explicit ordering is what's actually portable" reasoning this
        undo path already documents for InventoryMovement/SaleItem/Sale
        applies here too; Return must be deleted first, in the same
        explicit-order style, not left to a DB-level cascade that isn't
        configured."""
        if not sale_item_ids:
            return
        self.session.execute(delete(Return).where(Return.sale_item_id.in_(sale_item_ids)))
        self.session.flush()

    def count_in_range(self, business_id: uuid.UUID, start: datetime, end: datetime) -> int:
        total = self.session.scalar(
            select(func.count(Return.id))
            .join(SaleItem, SaleItem.id == Return.sale_item_id)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(Return.business_id == business_id, Sale.sold_at >= start, Sale.sold_at < end)
        )
        return int(total or 0)
