import uuid
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models.import_record import ImportRecord


class ImportRecordRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_for_business(self, record_id: uuid.UUID, business_id: uuid.UUID) -> ImportRecord | None:
        return self.session.scalar(
            select(ImportRecord).where(ImportRecord.id == record_id, ImportRecord.business_id == business_id)
        )

    def get_for_upload(self, upload_id: uuid.UUID, business_id: uuid.UUID) -> ImportRecord | None:
        # Exactly one ImportRecord per Upload in the current design — an
        # upload whose import has already run never goes back to "mapped",
        # so there's no re-run path that would create a second one.
        return self.session.scalar(
            select(ImportRecord).where(ImportRecord.upload_id == upload_id, ImportRecord.business_id == business_id)
        )

    def map_by_upload_id(self, business_id: uuid.UUID) -> dict[uuid.UUID, ImportRecord]:
        """One query for every ImportRecord in the business, keyed by
        upload_id — lets list_uploads attach each upload's import status
        without an N+1 query per row."""
        records = self.session.scalars(select(ImportRecord).where(ImportRecord.business_id == business_id))
        return {r.upload_id: r for r in records}

    def create(
        self,
        *,
        business_id: uuid.UUID,
        upload_id: uuid.UUID,
        mapping_profile_id: uuid.UUID,
        entity_type: str,
        status: str = "mapped",
    ) -> ImportRecord:
        # Each confirm-mapping call is "one attempt" (the model's own
        # docstring) — a new row every time, unlike the mapping profile
        # itself which is upserted per source.
        record = ImportRecord(
            business_id=business_id,
            upload_id=upload_id,
            mapping_profile_id=mapping_profile_id,
            entity_type=entity_type,
            status=status,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_after_import(
        self,
        record: ImportRecord,
        *,
        status: str,
        rows_total: int,
        rows_imported: int,
        rows_rejected: int,
        rejection_summary: dict | None,
    ) -> ImportRecord:
        # Flush only, not commit — app/imports/importer.py owns the single
        # commit for the whole write path (billing-style transaction
        # convention, see app/repositories/subscription.py). Do not add a
        # commit here; it would silently break the all-or-nothing guarantee.
        record.status = status
        record.rows_total = rows_total
        record.rows_imported = rows_imported
        record.rows_rejected = rows_rejected
        record.rejection_summary = rejection_summary
        self.session.flush()
        return record

    def mark_reversed(self, record: ImportRecord, *, reversed_at: datetime) -> ImportRecord:
        record.status = "reversed"
        record.reversed_at = reversed_at
        self.session.flush()
        return record

    def has_later_completed_inventory_import(self, business_id: uuid.UUID, after: datetime) -> bool:
        """The undo-ordering guard (app/imports/importer.py): an inventory
        reconciliation's movement magnitude bakes in every movement that
        preceded it (unlike a sales movement, which is independent) — so
        undoing anything that ran before a later completed reconciliation
        would silently corrupt the stock that reconciliation established.
        Business-wide, not per-product: cheap and guaranteed-safe beats a
        product-set-intersection query for marginal extra permissiveness.
        """
        return self.session.scalar(
            select(
                exists().where(
                    ImportRecord.business_id == business_id,
                    ImportRecord.entity_type == "inventory",
                    ImportRecord.status == "completed",
                    ImportRecord.reversed_at.is_(None),
                    ImportRecord.updated_at > after,
                )
            )
        )

    def latest_completed_by_entity_type(self, business_id: uuid.UUID) -> dict[str, datetime]:
        """The restock-freshness indicator (app/api/uploads.py's /freshness
        route): one grouped query returning each entity_type's most recent
        completed, unreversed import — a reversed import's data is no
        longer in effect, so it shouldn't count as "recently uploaded."
        """
        rows = self.session.execute(
            select(ImportRecord.entity_type, func.max(ImportRecord.updated_at))
            .where(
                ImportRecord.business_id == business_id,
                ImportRecord.status == "completed",
                ImportRecord.reversed_at.is_(None),
            )
            .group_by(ImportRecord.entity_type)
        ).all()
        return {entity_type: updated_at for entity_type, updated_at in rows}
