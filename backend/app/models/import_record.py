from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class ImportMappingProfile(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A saved column mapping for a given upload source, so the second
    upload from the same POS requires zero mapping input (PR-2.5).

    Unique on (business_id, source_signature): without it, "reuse the saved
    mapping for this source" would be ambiguous about which row to pick.
    """

    __tablename__ = "import_mapping_profiles"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "source_signature", name="uq_import_mapping_profiles_business_signature"
        ),
    )

    source_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    column_mapping: Mapped[dict] = mapped_column(JSON, nullable=False)


class ImportRecord(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """One attempt to turn an Upload into normalised rows in the canonical
    tables. Reversible (PR-2.11) and idempotent — see app/imports/.
    """

    __tablename__ = "import_records"

    upload_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("uploads.id"), nullable=False)
    mapping_profile_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_mapping_profiles.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejection_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
