from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class AuditLog(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Record of privileged actions — permission changes, billing events,
    deletions (PR-6.5). Written by application services, never edited.
    """

    __tablename__ = "audit_logs"

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
