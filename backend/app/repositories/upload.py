import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.upload import Upload


class UploadRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        storage_key: str,
        original_filename: str,
        uploaded_by: str,
        entity_type: str,
    ) -> Upload:
        upload = Upload(
            business_id=business_id,
            storage_key=storage_key,
            original_filename=original_filename,
            uploaded_by=uploaded_by,
            entity_type=entity_type,
            status="pending",
        )
        self.session.add(upload)
        self.session.commit()
        self.session.refresh(upload)
        return upload

    def get_for_business(self, upload_id: uuid.UUID, business_id: uuid.UUID) -> Upload | None:
        return self.session.scalar(
            select(Upload).where(Upload.id == upload_id, Upload.business_id == business_id)
        )

    def list_for_business(self, business_id: uuid.UUID) -> list[Upload]:
        return list(
            self.session.scalars(
                select(Upload)
                .where(Upload.business_id == business_id)
                .order_by(Upload.created_at.desc())
            )
        )

    def set_status(self, upload: Upload, *, status: str) -> Upload:
        upload.status = status
        self.session.commit()
        self.session.refresh(upload)
        return upload

    def set_status_flush_only(self, upload: Upload, *, status: str) -> Upload:
        # Used only by app/imports/importer.py, which owns the single
        # commit for the whole import write path — do not add a commit
        # here, it would break that all-or-nothing guarantee.
        upload.status = status
        self.session.flush()
        return upload
