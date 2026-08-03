import uuid

from sqlalchemy import delete
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
        reference_id: uuid.UUID | None,
    ) -> InventoryMovement:
        # Flush only — app/imports/importer.py owns the single commit.
        movement = InventoryMovement(
            business_id=business_id,
            product_id=product_id,
            quantity_delta=quantity_delta,
            reason=reason,
            reference_id=reference_id,
        )
        self.session.add(movement)
        self.session.flush()
        return movement

    def bulk_delete_by_reference_ids(self, sale_item_ids: list[uuid.UUID]) -> None:
        if not sale_item_ids:
            return
        self.session.execute(delete(InventoryMovement).where(InventoryMovement.reference_id.in_(sale_item_ids)))
        self.session.flush()
