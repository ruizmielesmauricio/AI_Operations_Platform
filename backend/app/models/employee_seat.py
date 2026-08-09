import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class EmployeeSeat(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A paid employee seat (€5/month, up to 2 per business) — the
    Membership that grants real access is only ever created once the
    seat's own Stripe subscription actually reaches "active"
    (app/billing/service.py's webhook handling), never at request time.
    A "pending_payment" row here with no matching Membership is exactly
    how "invited but hasn't paid yet" is represented — no separate flag
    needed on Membership itself.

    Mirrors a branch's own dedicated-Stripe-subscription pattern
    (app/models/business.py's parent_business_id) rather than a
    quantity-based line item on the business's existing subscription —
    there is no multi-item Stripe precedent anywhere in this codebase,
    and up to 2 seats is small enough that a second subscription per
    seat stays simple.
    """

    __tablename__ = "employee_seats"

    invited_by_user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    # Resolved from `email` at invite time — required (see product
    # decision: an employee must already have signed up before being
    # added; there is no invite-by-email/magic-link flow in this
    # codebase yet). This is who the eventual Membership.user_id will be.
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    surname: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Membership.ROLES minus "owner" — the account's existing owner is
    # already the admin (product decision); a new seat is manager or
    # staff.
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # "pending_payment" -> "active" (Membership created) on the seat's
    # Stripe subscription reaching active status; "payment_failed" or
    # "canceled" on anything else, which also removes the Membership if
    # one had been created — access tracks live payment status, not just
    # its first success.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_payment")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Unique, not composite with anything — a real Stripe subscription id
    # is globally unique. Nullable until Checkout completes. Deliberately
    # NOT unique on stripe_customer_id (unlike Subscription) — every seat
    # for a business reuses that business's own Stripe customer, since
    # the owner is who's actually paying.
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
