from datetime import datetime

from sqlalchemy import DECIMAL, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

"""Bicycle-shop template extension (Workshop Operations domain).

Deliberately modelled as a template-specific table, not the generalised
"Production Events" pattern proposed in 06_Database_Design.md — that
pattern is ADR-016, status Proposed, and its own risk note says not to
invest in the shared layer before a second vertical is being actively
built. This can migrate to Production Events later without customer-
visible impact, since it's an internal table.
"""


class Repair(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "repairs"

    customer_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    mechanic_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labour_cost: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    price_charged: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)


class RepairPartUsed(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "repair_parts_used"

    repair_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("repairs.id"), nullable=False, index=True)
    product_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_at_time: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
