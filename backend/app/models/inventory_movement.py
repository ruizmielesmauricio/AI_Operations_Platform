from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

REASONS = ("sale", "purchase", "adjustment", "return")


class InventoryMovement(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Stock level is derived by summing movements for a product, rather
    than maintained as a separate snapshot table — one source of truth,
    no risk of the two drifting apart. quantity_delta is negative for a
    sale, positive for a purchase/return.
    """

    __tablename__ = "inventory_movements"

    product_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
