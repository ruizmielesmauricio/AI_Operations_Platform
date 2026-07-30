from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Customer(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A canonical entity, industry-agnostic. Optional on sales/repairs —
    imported data frequently has no customer information at all.
    """

    __tablename__ = "customers"

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
