import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.analytics.types import ProductPeriodAggregate
from app.models.sale import Sale, SaleItem


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

    def list_product_ids_by_sale_ids(self, sale_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Read before app/imports/importer.py's _undo_sales_import deletes
        these rows — Stage C12 needs to know which products an undo
        touched, to refresh their low-stock alerts afterward. product_id
        is nullable on SaleItem, so unmatched-product rows are excluded
        (nothing to re-evaluate for a product that was never identified)."""
        if not sale_ids:
            return set()
        rows = self.session.scalars(
            select(SaleItem.product_id).where(SaleItem.sale_id.in_(sale_ids), SaleItem.product_id.isnot(None))
        )
        return set(rows)

    def bulk_delete_by_sale_ids(self, sale_ids: list[uuid.UUID]) -> None:
        if not sale_ids:
            return
        self.session.execute(delete(SaleItem).where(SaleItem.sale_id.in_(sale_ids)))
        self.session.flush()

    def aggregate_by_product_in_range(
        self, business_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[ProductPeriodAggregate]:
        """Per-product units/revenue/cost totals for [start, end), one
        query grouped by product_id (mirrors
        InventoryMovementRepository.sum_by_product_ids). Line items with no
        matched product_id (SaleItem.product_id is nullable) can't be
        attributed to any product and are excluded — a product missing
        from the result had either no sales or only unmatched-product
        sales in the period; callers must default missing keys themselves.

        revenue_with_known_cost/cogs only sum line items that have a
        cost_price_at_sale, so a product's margin is never computed
        against revenue it can't be matched to a cost for (PR-3.6).
        """
        known_cost = SaleItem.cost_price_at_sale.isnot(None)
        line_revenue = SaleItem.quantity * SaleItem.unit_price
        line_cost = SaleItem.quantity * SaleItem.cost_price_at_sale

        rows = self.session.execute(
            select(
                SaleItem.product_id,
                func.sum(SaleItem.quantity),
                func.sum(line_revenue),
                func.sum(case((known_cost, line_revenue), else_=0)),
                func.sum(case((known_cost, line_cost), else_=0)),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(
                SaleItem.business_id == business_id,
                SaleItem.product_id.isnot(None),
                Sale.sold_at >= start,
                Sale.sold_at < end,
            )
            .group_by(SaleItem.product_id)
        ).all()

        return [
            ProductPeriodAggregate(
                product_id=product_id,
                units_sold=int(units_sold),
                revenue=Decimal(revenue),
                revenue_with_known_cost=Decimal(revenue_with_known_cost),
                cogs=Decimal(cogs),
            )
            for product_id, units_sold, revenue, revenue_with_known_cost, cogs in rows
        ]
