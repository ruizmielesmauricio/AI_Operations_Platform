from datetime import datetime

from sqlalchemy import DECIMAL, DateTime, ForeignKey, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Sale(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "sales"

    customer_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_amount: Mapped[object] = mapped_column(DECIMAL(12, 2), nullable=False)


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
