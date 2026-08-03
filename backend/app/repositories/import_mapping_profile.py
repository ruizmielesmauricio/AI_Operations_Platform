import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.import_record import ImportMappingProfile


class ImportMappingProfileRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_signature(
        self, business_id: uuid.UUID, source_signature: str
    ) -> ImportMappingProfile | None:
        return self.session.scalar(
            select(ImportMappingProfile).where(
                ImportMappingProfile.business_id == business_id,
                ImportMappingProfile.source_signature == source_signature,
            )
        )

    def get_by_id(self, business_id: uuid.UUID, profile_id: uuid.UUID) -> ImportMappingProfile | None:
        return self.session.scalar(
            select(ImportMappingProfile).where(
                ImportMappingProfile.business_id == business_id,
                ImportMappingProfile.id == profile_id,
            )
        )

    def upsert(
        self, *, business_id: uuid.UUID, source_signature: str, column_mapping: dict
    ) -> ImportMappingProfile:
        """Tied to the source (signature), not the attempt — a re-confirm
        of the same source corrects the existing profile rather than
        creating a second, ambiguous one (PR-2.5)."""
        profile = self.get_by_signature(business_id, source_signature)
        if profile is None:
            profile = ImportMappingProfile(
                business_id=business_id,
                source_signature=source_signature,
                column_mapping=column_mapping,
            )
            self.session.add(profile)
        else:
            profile.column_mapping = column_mapping
        self.session.commit()
        self.session.refresh(profile)
        return profile
