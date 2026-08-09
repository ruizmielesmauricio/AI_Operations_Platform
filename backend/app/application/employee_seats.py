"""Orchestrates adding a paid employee seat (EUR 5/month, up to 2 per
business, PD-employee-seats). Route handlers stay thin (CLAUDE.md) — this
owns the actual rule: owner/admin-only, the seat cap, the existing-
account requirement (no invite-by-email/magic-link flow exists in this
codebase — product decision: the employee must already have signed up),
and the Stripe Checkout handoff.

Membership activation itself only ever happens from the webhook
(app/billing/service.py::_apply_employee_seat_event) — nothing on this
synchronous add_employee path creates a Membership, which is what makes
"no employee access before confirmed successful payment" actually hold.
"""

import uuid

from sqlalchemy.orm import Session

from app.billing.service import start_employee_seat_checkout
from app.models.employee_seat import EmployeeSeat
from app.models.membership import Membership
from app.models.user import User
from app.repositories.audit_log import record_audit_event
from app.repositories.employee_seat import EmployeeSeatRepository

MAX_EMPLOYEE_SEATS_PER_BUSINESS = 2
# Membership.ROLES minus "owner" — the account's existing owner is
# already treated as the admin role (product decision); a new seat is
# manager or staff.
EMPLOYEE_SEAT_ROLES = ("manager", "staff")


class InvalidEmployeeRole(Exception):
    """Raised when the requested role isn't manager/staff."""


class NoAccountForEmail(Exception):
    """Raised when the invited email has no existing User row — an
    employee must already have a Supabase-authenticated account (there's
    no invite-by-email/magic-link flow here yet). The API layer maps
    this to a 422 naming the real fix (sign up first, then retry)."""

    def __init__(self, email: str):
        self.email = email
        super().__init__(f"No account found for {email}")


class AlreadyAMemberOrInvited(Exception):
    """Raised when the invited email already has a reserved seat
    (pending or active) on this business, or is already a member some
    other way — never creates a second seat/subscription for one person."""

    def __init__(self, email: str):
        self.email = email
        super().__init__(f"{email} is already a member or has a pending invite on this business")


class EmployeeSeatLimitReached(Exception):
    """Raised at the product's stated cap (2 reserved seats/business)."""

    def __init__(self, business_id: uuid.UUID):
        self.business_id = business_id
        super().__init__(f"Business {business_id} already has {MAX_EMPLOYEE_SEATS_PER_BUSINESS} employee seats")


def add_employee(
    db: Session,
    *,
    business_id: uuid.UUID,
    business_email: str,
    invited_by_user_id: str,
    first_name: str,
    surname: str,
    email: str,
    role: str,
) -> tuple[EmployeeSeat, str]:
    """Returns the new (pending) seat and the Stripe Checkout URL to send
    the owner to next. Raises before creating anything if the request
    can't succeed — a rejected attempt leaves zero rows behind, same
    posture as app/repositories/business.py::create_business_with_owner.
    """
    if role not in EMPLOYEE_SEAT_ROLES:
        raise InvalidEmployeeRole(f"role must be one of {EMPLOYEE_SEAT_ROLES}")

    seats = EmployeeSeatRepository(db)
    if seats.count_reserved_for_business(business_id) >= MAX_EMPLOYEE_SEATS_PER_BUSINESS:
        raise EmployeeSeatLimitReached(business_id)

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise NoAccountForEmail(email)

    if seats.existing_reserved_seat_for_user(business_id, user.id) is not None:
        raise AlreadyAMemberOrInvited(email)
    already_a_member = (
        db.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == user.id)
        .first()
    )
    if already_a_member is not None:
        raise AlreadyAMemberOrInvited(email)

    seat = seats.create(
        business_id=business_id,
        invited_by_user_id=invited_by_user_id,
        user_id=user.id,
        first_name=first_name,
        surname=surname,
        email=email,
        role=role,
    )
    record_audit_event(
        db,
        business_id=business_id,
        user_id=invited_by_user_id,
        action="employee_invited",
        target_type="employee_seat",
        target_id=str(seat.id),
        metadata={"role": role},
    )
    checkout_url = start_employee_seat_checkout(
        db=db, business_id=business_id, employee_seat_id=seat.id, business_email=business_email
    )
    record_audit_event(
        db,
        business_id=business_id,
        user_id=invited_by_user_id,
        action="employee_payment_started",
        target_type="employee_seat",
        target_id=str(seat.id),
    )
    db.commit()
    db.refresh(seat)
    return seat, checkout_url
