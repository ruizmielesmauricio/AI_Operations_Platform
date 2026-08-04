import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantScopedMixin, TimestampMixin


class Subscription(Base, TimestampMixin, TenantScopedMixin):
    """One row per business — its Stripe subscription state. Status values
    mirror Stripe's own subscription status strings (see billing/status.py)
    rather than inventing a parallel vocabulary, so webhook payloads map
    onto this table with no translation layer to keep in sync.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("business_id", name="uq_subscriptions_business_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="incomplete")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessedStripeEvent(Base):
    """Records every Stripe webhook event id we've already acted on, so a
    retried delivery (Stripe retries on anything but a 2xx) never re-applies
    a state change — required for the "imports transactional and idempotent"
    non-negotiable to hold for webhooks too.
    """

    __tablename__ = "processed_stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
