import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.analytics.types import ProductPeriodAggregate
from app.models.product import Product
from app.models.sale import Sale, SaleItem

_SEARCH_LIMIT = 5


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
        tax_amount: Decimal | None = None,
    ) -> SaleItem:
        # Flush only — app/imports/importer.py owns the single commit.
        item = SaleItem(
            business_id=business_id,
            sale_id=sale_id,
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
            cost_price_at_sale=cost_price_at_sale,
            tax_amount=tax_amount,
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

        revenue_with_known_cost_and_tax/tax_amount_known/cogs_for_known_tax
        are the same idea one level stricter — cost known AND tax_amount
        known — so app/analytics/financial.py's net-of-tax margin never
        blends in a line whose revenue might still include tax.
        """
        known_cost = SaleItem.cost_price_at_sale.isnot(None)
        known_cost_and_tax = known_cost & SaleItem.tax_amount.isnot(None)
        line_revenue = SaleItem.quantity * SaleItem.unit_price
        line_cost = SaleItem.quantity * SaleItem.cost_price_at_sale

        rows = self.session.execute(
            select(
                SaleItem.product_id,
                func.sum(SaleItem.quantity),
                func.sum(line_revenue),
                func.sum(case((known_cost, line_revenue), else_=0)),
                func.sum(case((known_cost, line_cost), else_=0)),
                func.sum(case((known_cost_and_tax, line_revenue), else_=0)),
                func.sum(case((known_cost_and_tax, SaleItem.tax_amount), else_=0)),
                func.sum(case((known_cost_and_tax, line_cost), else_=0)),
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
                revenue_with_known_cost_and_tax=Decimal(revenue_with_known_cost_and_tax),
                tax_amount_known=Decimal(tax_amount_known),
                cogs_for_known_tax=Decimal(cogs_for_known_tax),
            )
            for (
                product_id,
                units_sold,
                revenue,
                revenue_with_known_cost,
                cogs,
                revenue_with_known_cost_and_tax,
                tax_amount_known,
                cogs_for_known_tax,
            ) in rows
        ]

    def list_units_by_product_in_range(
        self, business_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[uuid.UUID, datetime, int]]:
        """Every matched-product line item's (product_id, sold_at,
        quantity) in [start, end) — one query, not N+1. Raw rows only, no
        grouping (that's app/analytics/period.py::group_amounts_by_local_date's
        job, called once per product). Unmatched-product rows are excluded,
        same convention as aggregate_by_product_in_range above — there's no
        product to forecast demand for. Used by Stage C13's per-product
        demand forecast (app/application/forecast.py)."""
        rows = self.session.execute(
            select(SaleItem.product_id, Sale.sold_at, SaleItem.quantity)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(
                SaleItem.business_id == business_id,
                SaleItem.product_id.isnot(None),
                Sale.sold_at >= start,
                Sale.sold_at < end,
            )
        ).all()
        return [(product_id, sold_at, quantity) for product_id, sold_at, quantity in rows]

    def search_sales(
        self, business_id: uuid.UUID, query: str, *, limit: int = _SEARCH_LIMIT
    ) -> list[tuple[SaleItem, Sale, Product | None]]:
        """Backs the global search bar's "sales/orders" group — a single
        free-text term matched with OR across order_reference, the
        related product's name, and its SKU (deliberately OR, not the
        AND-per-named-filter shape list_paginated_for_business uses,
        since a search bar has exactly one field to type into, not
        several). Parameterized ILIKE only, same as every other search
        method in this codebase — never raw SQL. No customer PII: Sale
        carries no customer name/email, only a nullable customer_id FK
        that's never selected here.
        """
        needle = f"%{query.strip()}%"
        return [
            (item, sale, product)
            for item, sale, product in self.session.execute(
                select(SaleItem, Sale, Product)
                .join(Sale, Sale.id == SaleItem.sale_id)
                .outerjoin(Product, Product.id == SaleItem.product_id)
                .where(
                    SaleItem.business_id == business_id,
                    or_(
                        Sale.order_reference.ilike(needle),
                        Product.name.ilike(needle),
                        Product.sku.ilike(needle),
                    ),
                )
                .order_by(Sale.sold_at.desc(), SaleItem.id.desc())
                .limit(limit)
            ).all()
        ]

    def list_paginated_for_business(
        self,
        business_id: uuid.UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        product_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[tuple[SaleItem, Sale, Product | None]], int]:
        """Raw, one-line-item-per-row listing behind the dashboard's
        transaction drill-down (Gap 5) — deliberately separate from
        aggregate_by_product_in_range above, which only ever returns
        per-product sums. Every filter is optional and AND-ed together;
        category_id requires the outer join to Product since SaleItem
        has no category of its own. Most-recent-first, stable
        (Sale.sold_at, SaleItem.id) ordering so pagination never skips or
        repeats a row across pages even when several sales share a
        timestamp. `limit` is the caller's (API layer's) responsibility
        to cap — this method applies whatever it's given.
        """
        conditions = [SaleItem.business_id == business_id]
        if start is not None:
            conditions.append(Sale.sold_at >= start)
        if end is not None:
            conditions.append(Sale.sold_at < end)
        if product_id is not None:
            conditions.append(SaleItem.product_id == product_id)
        if category_id is not None:
            conditions.append(Product.category_id == category_id)

        base = (
            select(SaleItem, Sale, Product)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .outerjoin(Product, Product.id == SaleItem.product_id)
            .where(*conditions)
        )
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.execute(
            base.order_by(Sale.sold_at.desc(), SaleItem.id.desc()).limit(limit).offset(offset)
        ).all()
        return [(item, sale, product) for item, sale, product in rows], total
