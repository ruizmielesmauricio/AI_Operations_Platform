from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Uuid
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

    # The calendar date this movement's underlying event actually
    # happened — sale_date for a sale, purchase_date for a purchase, the
    # stock-count's as-of date for an adjustment (defaults to the upload's
    # processing date when the file doesn't carry one). NOT a UTC
    # timestamp conversion: these are plain business-local calendar dates
    # taken directly from the source file, same as ParsedSaleRow.sale_date/
    # ParsedPurchaseRow.purchase_date already are.
    #
    # This is what makes derived stock (InventoryMovementRepository.
    # sum_by_product_ids) order-independent — correct no matter what
    # sequence files get uploaded/processed in, which matters just as much
    # for a future automated feed as it does for today's manual uploads.
    # NULL on rows written before this field existed (backfilled
    # best-effort by the migration that added it) — treated as "always
    # include," the same behavior this system had before event_date
    # existed at all.
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Only ever set for reason="adjustment" rows — the exact count that
    # reconciliation established (the uploaded row's quantity_on_hand,
    # stored directly rather than re-derived later by re-summing history).
    # This, paired with event_date, is the baseline sum_by_product_ids
    # anchors to; quantity_delta on an adjustment row stays purely
    # informational (how big the correction was) once this is set.
    resulting_quantity_on_hand: Mapped[int | None] = mapped_column(Integer, nullable=True)
