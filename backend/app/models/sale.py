from datetime import datetime

from sqlalchemy import DECIMAL, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Sale(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "sales"

    customer_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_amount: Mapped[object] = mapped_column(DECIMAL(12, 2), nullable=False)
    # The source file's order/receipt/transaction id, if it has one — lets
    # B8 group several imported rows into one multi-item Sale instead of
    # always assuming one row = one sale. Optional: many small POS exports
    # genuinely are one row per sale and have nothing to put here.
    order_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Which import created this row, if any (nullable — a future manual
    # sale-entry feature won't have one). This is what undo (PR-2.11) uses
    # to find and remove exactly the rows one import created.
    import_record_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_records.id"), nullable=True, index=True
    )


class SaleItem(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """cost_price_at_sale is captured at import time so margin calculations
    on historical sales stay correct even after a product's current cost
    changes (see Product's docstring).
    """

    __tablename__ = "sale_items"

    sale_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales.id"), nullable=False, index=True)
    product_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[object] = mapped_column(DECIMAL(12, 2), nullable=False)
    cost_price_at_sale: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    # Optional, from a mapped Tax/VAT column — lets gross margin be
    # computed net of tax when known (app/analytics/financial.py's
    # net_gross_margin_pct), rather than assuming unit_price/total_amount
    # are already tax-exclusive.
    tax_amount: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
