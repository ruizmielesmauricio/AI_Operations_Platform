from sqlalchemy import String
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
