from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

REASONS = ("sale", "purchase", "adjustment", "return", "production_consumption", "production_output")


class InventoryMovement(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Stock level is derived by summing movements for a product, rather
    than maintained as a separate snapshot table — one source of truth,
    no risk of the two drifting apart. quantity_delta is negative for a
    sale or production_consumption, positive for a purchase/return/
    production_output, either sign for an adjustment (an inventory-upload
    reconciliation against the derived total).

    Provenance is a set of mutually exclusive nullable FKs, one per reason:
    - "sale" -> reference_id -> SaleItem -> Sale -> ImportRecord
      (app/imports/importer.py)
    - "adjustment" -> import_record_id (no SaleItem to reference)
    - "production_consumption" -> production_event_input_id (ADR-016;
      unused by any writer yet — Stage C9 calculation-phase work)
    - "production_output" -> production_event_output_id (ADR-016; same)
    Undo (PR-2.11) picks the right path per ImportRecord.entity_type.

    inventory_lot_id (ADR-022) is different in kind from the above: it is
    orthogonal to reason, not reason-gated — any movement can optionally
    tag the physical lot/batch it affected. Unused by any writer yet,
    reserved for future FEFO consumption logic.
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
    production_event_input_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_event_inputs.id"), nullable=True, index=True
    )
    production_event_output_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_event_outputs.id"), nullable=True, index=True
    )
    inventory_lot_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lots.id"), nullable=True, index=True
    )
    # The source file's PO/invoice number, if it has one — only ever set
    # for reason="purchase" rows written by the "purchases" upload entity
    # type. Combined with product_id (not alone — one PO covers several
    # products), lets a re-uploaded/overlapping file be rejected per row
    # instead of silently double-counting stock received (see
    # app/imports/importer.py's list_existing_purchase_reference_product_pairs).
    purchase_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
