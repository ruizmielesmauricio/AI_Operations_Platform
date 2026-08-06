import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
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

    def list_existing_order_references(self, business_id: uuid.UUID) -> set[str]:
        """Every non-null order_reference already used by this business,
        across all prior imports — one query, not N+1. Used to reject a
        re-uploaded/overlapping sales file per group instead of silently
        double-counting revenue (app/imports/importer.py::_write_sales)."""
        rows = self.session.scalars(
            select(Sale.order_reference).where(Sale.business_id == business_id, Sale.order_reference.isnot(None))
        )
        return set(rows)

    def list_amounts_in_range(
        self, business_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[datetime, Decimal]]:
        """Every sale's (sold_at, total_amount) in [start, end) — one query,
        not N+1. Raw rows only, no grouping/aggregation (that's
        app/analytics/period.py::group_amounts_by_local_date's job) — used
        by Stage C13's revenue forecast (app/application/forecast.py),
        which needs a per-day series, not the single period total
        sum_total_amount_in_range below returns."""
        rows = self.session.execute(
            select(Sale.sold_at, Sale.total_amount).where(
                Sale.business_id == business_id, Sale.sold_at >= start, Sale.sold_at < end
            )
        ).all()
        return [(sold_at, total_amount) for sold_at, total_amount in rows]

    def sum_total_amount_in_range(self, business_id: uuid.UUID, start: datetime, end: datetime) -> Decimal:
        """Total revenue for [start, end) — used as-is (Stage C9), rather
        than derived from sale_items, since a sale's total_amount is the
        authoritative figure and doesn't depend on every line item having
        a matched product (see SaleItemRepository.aggregate_by_product_in_range,
        which does exclude unmatched line items)."""
        total = self.session.scalar(
            select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
                Sale.business_id == business_id, Sale.sold_at >= start, Sale.sold_at < end
            )
        )
        return Decimal(total)
