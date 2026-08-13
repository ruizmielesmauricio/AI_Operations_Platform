from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Local mirror of a Supabase Auth identity. id matches the Supabase
    auth user id (the JWT's `sub` claim) exactly — this table holds
    app-level profile data only; Supabase Auth remains the source of truth
    for credentials and sessions (ADR-013).
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    # ORLA-level immediate session invalidation. Supabase revokes refresh
    # tokens, but a previously issued access JWT remains cryptographically
    # valid until its expiry. These fields let ORLA reject every old session
    # at its own API boundary immediately after a password reset, while
    # allowing the recovery session that performed the reset to continue.
    session_revoked_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_exception_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
