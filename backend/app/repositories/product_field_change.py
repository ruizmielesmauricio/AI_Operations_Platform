import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product_field_change import ProductFieldChange


class ProductFieldChangeRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_import_newest_first(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> list[ProductFieldChange]:
        return list(
            self.session.scalars(
                select(ProductFieldChange)
                .where(
                    ProductFieldChange.business_id == business_id,
                    ProductFieldChange.import_record_id == import_record_id,
                    ProductFieldChange.status == "applied",
                )
                .order_by(ProductFieldChange.created_at.desc())
            )
        )

    def later_applied_changes(self, change: ProductFieldChange) -> list[ProductFieldChange]:
        """Changes to the same product field made AFTER `change` by a
        different, still-in-effect import, oldest first."""
        return list(
            self.session.scalars(
                select(ProductFieldChange)
                .where(
                    ProductFieldChange.business_id == change.business_id,
                    ProductFieldChange.product_id == change.product_id,
                    ProductFieldChange.field == change.field,
                    ProductFieldChange.import_record_id != change.import_record_id,
                    ProductFieldChange.status == "applied",
                    ProductFieldChange.created_at > change.created_at,
                )
                .order_by(ProductFieldChange.created_at.asc())
            )
        )

    def counts_by_status(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> dict[str, int]:
        rows = self.session.execute(
            select(ProductFieldChange.status, func.count())
            .where(ProductFieldChange.business_id == business_id, ProductFieldChange.import_record_id == import_record_id)
            .group_by(ProductFieldChange.status)
        ).all()
        return {status: count for status, count in rows}
