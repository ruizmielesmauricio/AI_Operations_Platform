from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Upload(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A file the customer uploaded to R2, before it's been parsed into an
    Import. The underlying object is deleted after successful ingestion
    (ADR-008) — this row is what remains as the audit trail.
    """

    __tablename__ = "uploads"

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
