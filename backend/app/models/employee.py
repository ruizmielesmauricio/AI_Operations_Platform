from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Employee(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A canonical entity. In the bicycle-shop template this is who a
    Repair's mechanic field points at; other templates reuse it for their
    own production-event performer without a schema change.
    """

    __tablename__ = "employees"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
