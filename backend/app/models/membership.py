from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

ROLES = ("owner", "manager", "staff")


class Membership(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Links a user to a business with a role. This is the table every
    tenant-isolation check ultimately resolves against — see
    app/security/tenant.py (PR-6.1/6.2).
    """

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("business_id", "user_id", name="uq_membership_business_user"),)

    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
