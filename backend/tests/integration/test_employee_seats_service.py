from types import SimpleNamespace

import pytest

from app.application.employee_seats import (
    AlreadyAMemberOrInvited,
    EmployeeSeatLimitReached,
    EmployeeSeatNotFound,
    InvalidEmployeeRole,
    MAX_EMPLOYEE_SEATS_PER_BUSINESS,
    add_employee,
    try_activate_employee_seat,
    update_employee_profile,
)
from app.billing import client
from app.models.membership import Membership
from app.models.user import User
from app.repositories.employee_seat import EmployeeSeatRepository
from app.settings.config import get_settings


@pytest.fixture(autouse=True)
def _seat_price(monkeypatch):
    monkeypatch.setenv("STRIPE_EMPLOYEE_SEAT_PRICE_ID", "price_employee_seat")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fake_checkout(monkeypatch):
    def fake_create_checkout_session(
        *,
        business_id,
        business_email,
        success_url,
        cancel_url,
        price_id,
        existing_stripe_customer_id=None,
        extra_metadata=None,
    ):
        return SimpleNamespace(url=f"https://checkout.stripe.com/fake?seat={extra_metadata.get('employee_seat_id')}")

    monkeypatch.setattr(client, "create_checkout_session", fake_create_checkout_session)


def _seed_user(db_session, user_id, email):
    db_session.add(User(id=user_id, email=email))
    db_session.commit()


def test_add_employee_does_not_require_an_existing_account(db_session, business_id):
    # Direct product-direction change: the owner creates the profile
    # directly, no pre-existing account required — this used to raise
    # NoAccountForEmail; now it just creates an unlinked pending seat.
    _seed_user(db_session, "owner-1", "owner@shopa.example")

    seat, checkout_url = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="never-signed-up@shopa.example",
        role="staff",
    )

    assert seat.status == "pending_payment"
    assert seat.user_id is None
    assert "checkout.stripe.com" in checkout_url


def test_add_employee_links_immediately_when_the_account_already_exists(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    _seed_user(db_session, "employee-1", "employee@shopa.example")

    seat, _ = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role="staff",
    )

    assert seat.user_id == "employee-1"


def test_add_employee_matches_an_existing_account_case_insensitively(db_session, business_id):
    # The real reported bug: an owner adding someone who had genuinely
    # already signed up got "No account found" purely from a casing
    # mismatch between what was typed and what Supabase/Google returned.
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    _seed_user(db_session, "employee-1", "macob39@gmail.com")

    seat, _ = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Mac",
        surname="OBrien",
        email="MacOB39@Gmail.com",
        role="staff",
    )

    assert seat.user_id == "employee-1"


def test_add_employee_persists_address_fields(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")

    seat, _ = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role="staff",
        address_line1="12 Main Street",
        city="Dublin",
        postal_code="D06",
        country="Ireland",
    )

    assert seat.address_line1 == "12 Main Street"
    assert seat.city == "Dublin"
    assert seat.postal_code == "D06"
    assert seat.country == "Ireland"


def test_a_third_employee_is_rejected(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    for i in range(MAX_EMPLOYEE_SEATS_PER_BUSINESS):
        add_employee(
            db_session,
            business_id=business_id,
            business_email="owner@shopa.example",
            invited_by_user_id="owner-1",
            first_name="Employee",
            surname=str(i),
            email=f"employee{i}@shopa.example",
            role="staff",
        )

    with pytest.raises(EmployeeSeatLimitReached):
        add_employee(
            db_session,
            business_id=business_id,
            business_email="owner@shopa.example",
            invited_by_user_id="owner-1",
            first_name="Extra",
            surname="Person",
            email="extra@shopa.example",
            role="staff",
        )


def test_rejects_re_inviting_an_already_reserved_email(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role="staff",
    )

    with pytest.raises(AlreadyAMemberOrInvited):
        add_employee(
            db_session,
            business_id=business_id,
            business_email="owner@shopa.example",
            invited_by_user_id="owner-1",
            first_name="Aoife",
            surname="Byrne",
            email="employee@shopa.example",
            role="manager",
        )


def test_rejects_an_invalid_role(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")

    with pytest.raises(InvalidEmployeeRole):
        add_employee(
            db_session,
            business_id=business_id,
            business_email="owner@shopa.example",
            invited_by_user_id="owner-1",
            first_name="Aoife",
            surname="Byrne",
            email="employee@shopa.example",
            role="owner",
        )


def test_try_activate_requires_both_payment_and_a_linked_account(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    seat, _ = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role="staff",
    )

    # Neither paid nor linked yet.
    assert try_activate_employee_seat(db_session, seat) is False

    seat.status = "active"
    db_session.commit()
    # Paid, but still not linked to a real account.
    assert try_activate_employee_seat(db_session, seat) is False

    _seed_user(db_session, "employee-1", "employee@shopa.example")
    EmployeeSeatRepository(db_session).link_user(seat, "employee-1")
    db_session.commit()
    # Now both conditions hold.
    assert try_activate_employee_seat(db_session, seat) is True
    membership = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership is not None
    assert membership.role == "staff"
    # Idempotent — calling again does nothing further.
    assert try_activate_employee_seat(db_session, seat) is False


def test_update_employee_profile_persists_first_name_and_surname_separately(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    seat, _ = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role="staff",
    )

    updated = update_employee_profile(
        db_session,
        business_id=business_id,
        seat_id=seat.id,
        editing_user_id="owner-1",
        first_name="Aoibhinn",
        surname="Byrne-Walsh",
        role="manager",
        address_line1="1 Grafton Street",
        city="Dublin",
        postal_code="D02",
        country="Ireland",
    )

    assert updated.first_name == "Aoibhinn"
    assert updated.surname == "Byrne-Walsh"
    assert updated.role == "manager"
    assert updated.address_line1 == "1 Grafton Street"


def test_editing_an_active_seat_updates_the_live_membership_role(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    _seed_user(db_session, "employee-1", "employee@shopa.example")
    seat, _ = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role="staff",
    )
    seat.status = "active"
    db_session.commit()
    try_activate_employee_seat(db_session, seat)
    db_session.commit()

    update_employee_profile(
        db_session,
        business_id=business_id,
        seat_id=seat.id,
        editing_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        role="manager",
        address_line1=None,
        city=None,
        postal_code=None,
        country=None,
    )

    membership = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership.role == "manager"


def test_editing_a_nonexistent_seat_raises(db_session, business_id):
    import uuid

    _seed_user(db_session, "owner-1", "owner@shopa.example")
    with pytest.raises(EmployeeSeatNotFound):
        update_employee_profile(
            db_session,
            business_id=business_id,
            seat_id=uuid.uuid4(),
            editing_user_id="owner-1",
            first_name="X",
            surname="Y",
            role="staff",
            address_line1=None,
            city=None,
            postal_code=None,
            country=None,
        )
