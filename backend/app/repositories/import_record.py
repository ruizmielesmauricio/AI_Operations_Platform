import uuid
from datetime import datetime

from sqlalchemy import select
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

    def create(
        self,
        *,
        business_id: uuid.UUID,
        upload_id: uuid.UUID,
        mapping_profile_id: uuid.UUID,
        status: str = "mapped",
    ) -> ImportRecord:
        # Each confirm-mapping call is "one attempt" (the model's own
        # docstring) — a new row every time, unlike the mapping profile
        # itself which is upserted per source.
        record = ImportRecord(
            business_id=business_id,
            upload_id=upload_id,
            mapping_profile_id=mapping_profile_id,
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
