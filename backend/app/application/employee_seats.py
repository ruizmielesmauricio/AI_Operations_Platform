"""Orchestrates paid employee seats (EUR 5/month, up to 2 per business,
PD-employee-seats). Route handlers stay thin (CLAUDE.md) — this owns the
actual rules: owner/admin-only, the seat cap, and the two independent
events that must both happen before real access is granted.

Product direction: the owner/admin creates the employee's profile
directly — the employee does NOT need an existing account first (a real
bug report showed requiring one was real friction: an owner adding
someone who'd genuinely already signed up got "No account found" purely
from an email-casing mismatch). A seat's `user_id` starts NULL and gets
linked automatically the first time that email authenticates
(reconcile_pending_employee_seats, called from
app/security/auth.py::get_current_user_synced). Real access
(a Membership row) is only ever granted once a seat is BOTH linked to a
user AND its Stripe subscription is "active" — whichever of the two
happens second is what actually activates it (try_activate_employee_seat,
shared with the webhook in app/billing/service.py).
"""

import uuid
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.application.notifications import (
    notify_employee_activated,
    notify_employee_added,
    notify_employee_removed,
    notify_employee_role_changed,
)
from app.billing import client as billing_client
from app.email.service import send_employee_invite_email
from app.models.business import Business
from app.models.employee_seat import EmployeeSeat
from app.models.membership import Membership
from app.models.user import User
from app.repositories.audit_log import record_audit_event
from app.repositories.employee_seat import EmployeeSeatRepository
from app.settings.config import get_settings

MAX_EMPLOYEE_SEATS_PER_BUSINESS = 2
# Membership.ROLES minus "owner" — the account's existing owner is
# already treated as the admin role (product decision); a new seat is
# manager or staff.
EMPLOYEE_SEAT_ROLES = ("manager", "staff")


class InvalidEmployeeRole(Exception):
    """Raised when the requested role isn't manager/staff."""


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


class EmployeeSeatNotFound(Exception):
    """Raised editing a seat id that doesn't exist on this business."""


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
    address_line1: str | None = None,
    city: str | None = None,
    postal_code: str | None = None,
    country: str | None = None,
) -> tuple[EmployeeSeat, str]:
    """Returns the new (pending) seat and the Stripe Checkout URL to send
    the owner to next. Raises before creating anything if the request
    can't succeed — a rejected attempt leaves zero rows behind, same
    posture as app/repositories/business.py::create_business_with_owner.

    If a User with a matching email (case-insensitive) already exists,
    the seat is linked immediately — no need to wait for a future login
    in that case.
    """
    # Local import: app/billing/service.py imports back from this module
    # (try_activate_employee_seat, for its webhook handler) — deferring
    # this one import to call time avoids a circular import at module
    # load, since Python only needs the name resolved when add_employee
    # actually runs, by which point both modules are fully loaded.
    from app.billing.service import start_employee_seat_checkout

    if role not in EMPLOYEE_SEAT_ROLES:
        raise InvalidEmployeeRole(f"role must be one of {EMPLOYEE_SEAT_ROLES}")

    seats = EmployeeSeatRepository(db)
    if seats.count_reserved_for_business(business_id) >= MAX_EMPLOYEE_SEATS_PER_BUSINESS:
        raise EmployeeSeatLimitReached(business_id)
    if seats.existing_reserved_seat_for_email(business_id, email) is not None:
        raise AlreadyAMemberOrInvited(email)

    existing_user = db.query(User).filter(User.email.ilike(email)).first()
    if existing_user is not None:
        already_a_member = (
            db.query(Membership)
            .filter(Membership.business_id == business_id, Membership.user_id == existing_user.id)
            .first()
        )
        if already_a_member is not None:
            raise AlreadyAMemberOrInvited(email)

    seat = seats.create(
        business_id=business_id,
        invited_by_user_id=invited_by_user_id,
        user_id=existing_user.id if existing_user else None,
        first_name=first_name,
        surname=surname,
        email=email,
        role=role,
        address_line1=address_line1,
        city=city,
        postal_code=postal_code,
        country=country,
    )
    record_audit_event(
        db,
        business_id=business_id,
        user_id=invited_by_user_id,
        action="employee_profile_created",
        target_type="employee_seat",
        target_id=str(seat.id),
        metadata={"role": role, "linked_immediately": existing_user is not None},
    )
    notify_employee_added(db, business_id=business_id, seat_id=seat.id, full_name=f"{first_name} {surname}")
    # Only a real invite when nobody with this email exists yet — an
    # already-existing, already-linked account doesn't need a "come
    # register" email, since reconciliation already happened at creation
    # time above.
    if existing_user is None:
        business = db.get(Business, business_id)
        business_name = business.name if business is not None else "your team"
        registration_url = f"{get_settings().app_base_url}/signup?{urlencode({'email': email})}"
        if send_employee_invite_email(
            to_email=email, business_name=business_name, registration_url=registration_url
        ):
            record_audit_event(
                db,
                business_id=business_id,
                user_id=invited_by_user_id,
                action="employee_invite_email_sent",
                target_type="employee_seat",
                target_id=str(seat.id),
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


def update_employee_profile(
    db: Session,
    *,
    business_id: uuid.UUID,
    seat_id: uuid.UUID,
    editing_user_id: str,
    first_name: str,
    surname: str,
    role: str,
    address_line1: str | None,
    city: str | None,
    postal_code: str | None,
    country: str | None,
) -> EmployeeSeat:
    if role not in EMPLOYEE_SEAT_ROLES:
        raise InvalidEmployeeRole(f"role must be one of {EMPLOYEE_SEAT_ROLES}")

    seats = EmployeeSeatRepository(db)
    seat = seats.get_for_business(seat_id, business_id)
    if seat is None:
        raise EmployeeSeatNotFound(str(seat_id))
    previous_role = seat.role

    seats.update_profile(
        seat,
        first_name=first_name,
        surname=surname,
        role=role,
        address_line1=address_line1,
        city=city,
        postal_code=postal_code,
        country=country,
    )
    if previous_role != role:
        notify_employee_role_changed(
            db, business_id=business_id, seat_id=seat.id, full_name=f"{first_name} {surname}", new_role=role
        )
    # If the seat is already active, its live Membership.role must track
    # the edit too — otherwise editing a seat's role would silently stop
    # meaning anything once payment had already succeeded.
    if seat.user_id is not None:
        membership = (
            db.query(Membership)
            .filter(Membership.business_id == business_id, Membership.user_id == seat.user_id)
            .first()
        )
        if membership is not None:
            membership.role = role
    record_audit_event(
        db,
        business_id=business_id,
        user_id=editing_user_id,
        action="employee_profile_edited",
        target_type="employee_seat",
        target_id=str(seat.id),
        metadata={"role": role},
    )
    db.commit()
    db.refresh(seat)
    return seat


def get_own_employee_seat(db: Session, *, business_id: uuid.UUID, user_id: str) -> EmployeeSeat:
    """The staff self-profile route's read side (GET .../me). Raises
    EmployeeSeatNotFound for an owner (who has no EmployeeSeat row at
    all — their own profile lives on the Business record itself, edited
    through the owner-only company-profile PATCH instead)."""
    seat = EmployeeSeatRepository(db).get_for_business_and_user(business_id, user_id)
    if seat is None:
        raise EmployeeSeatNotFound(f"No employee profile for user {user_id} at business {business_id}")
    return seat


def update_own_employee_profile(
    db: Session,
    *,
    business_id: uuid.UUID,
    user_id: str,
    first_name: str,
    surname: str,
    address_line1: str | None,
    city: str | None,
    postal_code: str | None,
    country: str | None,
) -> EmployeeSeat:
    """The staff self-profile route's write side (PATCH .../me) —
    deliberately has no role/status/email parameter to pass through at
    all, unlike update_employee_profile above: a staff member editing
    themselves can only ever reach EmployeeSeatRepository.update_self_profile,
    which has the same restriction built in one layer down."""
    seats = EmployeeSeatRepository(db)
    seat = seats.get_for_business_and_user(business_id, user_id)
    if seat is None:
        raise EmployeeSeatNotFound(f"No employee profile for user {user_id} at business {business_id}")

    seats.update_self_profile(
        seat, first_name=first_name, surname=surname, address_line1=address_line1,
        city=city, postal_code=postal_code, country=country,
    )
    record_audit_event(
        db,
        business_id=business_id,
        user_id=user_id,
        action="employee_self_profile_updated",
        target_type="employee_seat",
        target_id=str(seat.id),
    )
    db.commit()
    db.refresh(seat)
    return seat


def delete_employee(db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID, deleting_user_id: str) -> EmployeeSeat:
    """Owner-only deletion/deactivation (enforced by the caller — the API
    route — not here, same split as every other route in this module).
    Never a hard delete: the seat row stays (this codebase's usual
    audit-log-conscious posture, e.g. app/repositories/business.py::
    soft_delete_business) with status "canceled", the same terminal
    status a failed/cancelled payment already uses — reusing that
    vocabulary rather than inventing a distinct "deleted" state, since
    the practical effect (no access, no active billing) is identical.

    Idempotent: calling this on an already-canceled seat is a no-op that
    still returns the seat, never a second Stripe cancel call or a
    second audit entry.
    """
    seats = EmployeeSeatRepository(db)
    seat = seats.get_for_business(seat_id, business_id)
    if seat is None:
        raise EmployeeSeatNotFound(str(seat_id))
    if seat.status == "canceled":
        return seat

    if seat.stripe_subscription_id:
        billing_client.cancel_subscription(seat.stripe_subscription_id)
    revoke_employee_membership(db, seat)
    seats.set_status(seat, "canceled")
    record_audit_event(
        db,
        business_id=business_id,
        user_id=deleting_user_id,
        action="employee_deleted",
        target_type="employee_seat",
        target_id=str(seat.id),
    )
    notify_employee_removed(db, business_id=business_id, seat_id=seat.id, full_name=f"{seat.first_name} {seat.surname}")
    db.commit()
    db.refresh(seat)
    return seat


def try_activate_employee_seat(db: Session, seat: EmployeeSeat) -> bool:
    """The one place a seat's Membership actually gets created — called
    from both directions that can complete activation: the payment
    webhook (app/billing/service.py, once status becomes "active") and
    reconcile_pending_employee_seats below (once user_id gets linked).
    Idempotent either way: returns True only the moment it actually
    creates the Membership, never on a call that finds one already there
    or isn't ready yet.
    """
    if seat.status != "active" or seat.user_id is None:
        return False
    existing = (
        db.query(Membership)
        .filter(Membership.business_id == seat.business_id, Membership.user_id == seat.user_id)
        .first()
    )
    if existing is not None:
        return False
    db.add(Membership(business_id=seat.business_id, user_id=seat.user_id, role=seat.role))
    notify_employee_activated(
        db, business_id=seat.business_id, seat_id=seat.id, full_name=f"{seat.first_name} {seat.surname}"
    )
    db.flush()
    return True


def revoke_employee_membership(db: Session, seat: EmployeeSeat) -> None:
    if seat.user_id is None:
        return
    membership = (
        db.query(Membership)
        .filter(Membership.business_id == seat.business_id, Membership.user_id == seat.user_id)
        .first()
    )
    if membership is not None:
        db.delete(membership)
        db.flush()


def reconcile_pending_employee_seats(db: Session, user: User) -> None:
    """Called from get_current_user_synced on every authenticated
    request — cheap at this app's scale (a handful of pending seats at
    most), and the only point guaranteed to fire the moment a
    newly-invited employee's email actually authenticates for the first
    time, without needing a dedicated "accept invite" click.
    """
    seats = EmployeeSeatRepository(db)
    pending = seats.list_unlinked_pending_by_email(user.email)
    if not pending:
        return
    for seat in pending:
        seats.link_user(seat, user.id)
        # Distinct from "membership_activated" below — registering is
        # its own milestone regardless of whether payment has also
        # succeeded yet (it may not have: the owner could still be
        # completing Checkout, or it could have failed).
        record_audit_event(
            db,
            business_id=seat.business_id,
            user_id=seat.invited_by_user_id,
            action="employee_registration_completed",
            target_type="employee_seat",
            target_id=str(seat.id),
        )
        if try_activate_employee_seat(db, seat):
            record_audit_event(
                db,
                business_id=seat.business_id,
                user_id=seat.invited_by_user_id,
                action="employee_membership_activated",
                target_type="employee_seat",
                target_id=str(seat.id),
            )
    db.commit()
