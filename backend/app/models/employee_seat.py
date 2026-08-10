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
    # Nullable — the owner/admin creates the profile directly; the
    # employee does NOT need an existing account first (product
    # direction: avoid requiring staff to sign up independently first).
    # Resolved immediately at creation time if a User with a matching
    # email (case-insensitive) already exists; otherwise linked later,
    # automatically, the first time that email authenticates
    # (app/application/employee_seats.py::reconcile_pending_employee_seats,
    # called from get_current_user_synced). Membership is only ever
    # created once BOTH this is set AND status == "active" — whichever
    # of "paid" and "linked" happens second is what actually activates.
    user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    surname: Mapped[str] = mapped_column(String(128), nullable=False)
    # Case is preserved as typed for display, but every lookup/match
    # against this (reconciliation, "already invited" check) normalizes
    # to lowercase first — email is conventionally case-insensitive
    # (Gmail always is), and comparing raw case caused a real bug: an
    # owner adding someone who'd already signed up got "No account
    # found" purely because of a casing mismatch.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Membership.ROLES minus "owner" — the account's existing owner is
    # already the admin (product decision); a new seat is manager or
    # staff.
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # "pending_payment" -> "active" (Membership created, once user_id is
    # also set) on the seat's Stripe subscription reaching active status;
    # "payment_failed" or "canceled" on anything else, which also removes
    # the Membership if one had been created — access tracks live payment
    # status, not just its first success.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_payment")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Unique, not composite with anything — a real Stripe subscription id
    # is globally unique. Nullable until Checkout completes. Deliberately
    # NOT unique on stripe_customer_id (unlike Subscription) — every seat
    # for a business reuses that business's own Stripe customer, since
    # the owner is who's actually paying.
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    # Optional profile fields, consistent with the owner/business profile
    # (app/models/business.py) — same live Geoapify-suggestion input on
    # the frontend. No timezone field: that's a business-level setting,
    # not a personal one.
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
