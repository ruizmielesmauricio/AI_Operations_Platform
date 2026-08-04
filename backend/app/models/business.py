from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Business(Base, PKMixin, TimestampMixin):
    """The tenant root. Every other table scopes itself to a business via
    business_id (see TenantScopedMixin) — this is the row that id refers to.
    """

    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False, default="bicycle_shop")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Dublin")
