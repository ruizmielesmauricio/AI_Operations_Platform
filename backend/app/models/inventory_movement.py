from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

REASONS = ("sale", "purchase", "adjustment", "return")


class InventoryMovement(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Stock level is derived by summing movements for a product, rather
    than maintained as a separate snapshot table — one source of truth,
    no risk of the two drifting apart. quantity_delta is negative for a
    sale, positive for a purchase/return, either sign for an adjustment
    (an inventory-upload reconciliation against the derived total).

    Two mutually exclusive provenance paths, by reason: a "sale" movement
    traces back via reference_id -> SaleItem -> Sale -> ImportRecord
    (app/imports/importer.py); an "adjustment" movement (no SaleItem to
    reference) traces directly via import_record_id instead. Undo
    (PR-2.11) picks the right path per ImportRecord.entity_type.
    """

    __tablename__ = "inventory_movements"

    product_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sale_items.id"), nullable=True
    )
    import_record_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_records.id"), nullable=True, index=True
    )
