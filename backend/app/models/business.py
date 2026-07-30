import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Business(Base, TimestampMixin):
    """The tenant root. Every other table scopes itself to a business via
    business_id (see TenantScopedMixin) — this is the row that id refers to.
    """

    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False, default="bicycle_shop")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Dublin")
