import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.inventory_movement import InventoryMovement


class InventoryMovementRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity_delta: int,
        reason: str,
        reference_id: uuid.UUID | None = None,
        import_record_id: uuid.UUID | None = None,
        purchase_reference: str | None = None,
    ) -> InventoryMovement:
        # Flush only — app/imports/importer.py owns the single commit.
        movement = InventoryMovement(
            business_id=business_id,
            product_id=product_id,
            quantity_delta=quantity_delta,
            reason=reason,
            reference_id=reference_id,
            import_record_id=import_record_id,
            purchase_reference=purchase_reference,
        )
        self.session.add(movement)
        self.session.flush()
        return movement

    def sum_by_product_ids(self, business_id: uuid.UUID, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Current derived stock for each product — one query, not N+1.
        A product with no rows here (never had a movement) has 0 stock;
        callers must default missing keys themselves."""
        if not product_ids:
            return {}
        rows = self.session.execute(
            select(InventoryMovement.product_id, func.sum(InventoryMovement.quantity_delta))
            .where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.product_id.in_(product_ids),
            )
            .group_by(InventoryMovement.product_id)
        ).all()
        return {product_id: int(total) for product_id, total in rows}

    def bulk_delete_by_reference_ids(self, sale_item_ids: list[uuid.UUID]) -> None:
        if not sale_item_ids:
            return
        self.session.execute(delete(InventoryMovement).where(InventoryMovement.reference_id.in_(sale_item_ids)))
        self.session.flush()

    def bulk_delete_by_import_record_id(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> None:
        self.session.execute(
            delete(InventoryMovement).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.import_record_id == import_record_id,
            )
        )
        self.session.flush()

    def list_existing_purchase_reference_product_pairs(self, business_id: uuid.UUID) -> set[tuple[str, uuid.UUID]]:
        """Every non-null (purchase_reference, product_id) pair already
        used by this business's purchase movements, across all prior
        imports — one query, not N+1. Used to reject a re-uploaded/
        overlapping purchases file per row instead of silently double-
        counting stock received (app/imports/importer.py::_write_purchases).

        Keyed by reference AND product, not reference alone — a single PO
        / invoice routinely covers several different products in one
        purchase, so two rows sharing a reference are not automatically
        duplicates of each other."""
        rows = self.session.execute(
            select(InventoryMovement.purchase_reference, InventoryMovement.product_id).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.reason == "purchase",
                InventoryMovement.purchase_reference.isnot(None),
            )
        ).all()
        return {(ref, product_id) for ref, product_id in rows}

    def list_product_ids_by_import_record_id(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> set[uuid.UUID]:
        """Read before app/imports/importer.py's _undo_inventory_import
        deletes these rows — Stage C12 needs to know which products an
        undo touched, to refresh their low-stock alerts afterward."""
        rows = self.session.scalars(
            select(InventoryMovement.product_id).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.import_record_id == import_record_id,
            )
        )
        return set(rows)
