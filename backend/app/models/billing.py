from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class BillingAccount(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Local mirror of Stripe subscription state (PR-7). Paid access is
    granted only from verified webhooks, never from this table being
    written by anything other than the billing module (app/billing/).
    """

    __tablename__ = "billing_accounts"

    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
