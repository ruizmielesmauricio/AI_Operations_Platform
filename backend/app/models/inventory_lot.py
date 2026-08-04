from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class InventoryLot(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Canonical inventory-layer extension (ADR-022) — not pharmacy-specific.
    Lot/batch identity and an optional expiry date for any perishable or
    shelf-life-bound product: pharmacy prescriptions, cafe perishables,
    bike-shop consumables (e.g. brake fluid) tracked for recall purposes.

    Deliberately minimal: no FEFO (first-expiry-first-out) consumption
    logic here, and inventory_movements.inventory_lot_id (the FK that will
    eventually tie a stock movement to a specific lot) is unused by any
    writer yet — that's Stage C9 calculation-phase work.
    """

    __tablename__ = "inventory_lots"
    __table_args__ = (
        UniqueConstraint("business_id", "product_id", "lot_number", name="uq_inventory_lots_business_product_lot"),
    )

    product_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    lot_number: Mapped[str] = mapped_column(String(128), nullable=False)
    # Nullable — some tracked lots (e.g. bike-shop consumables) care about
    # recall traceability, not an expiry date.
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
