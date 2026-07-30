import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Uuid, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.settings.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class PKMixin:
    """UUID primary key, generated in Python (not a Postgres-only extension
    like pgcrypto) so it works identically on Neon and any other backend.
    Uses SQLAlchemy's cross-dialect Uuid type — native UUID on Postgres,
    a portable representation elsewhere — so the same models are usable
    against SQLite in tests without a live database server.
    """

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """created_at/updated_at, always stored in UTC per project convention."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TenantScopedMixin:
    """Every table that holds business data mixes this in, per CLAUDE.md's
    non-negotiable: 'Tenant-scope every table via business_id.' The root
    Business table itself does not use this mixin — everything else does.
    """

    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("businesses.id"), index=True, nullable=False
    )
