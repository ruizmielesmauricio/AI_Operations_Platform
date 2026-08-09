from types import SimpleNamespace

import pytest

from app.application.employee_seats import (
    AlreadyAMemberOrInvited,
    EmployeeSeatLimitReached,
    InvalidEmployeeRole,
    MAX_EMPLOYEE_SEATS_PER_BUSINESS,
    NoAccountForEmail,
    add_employee,
)
from app.billing import client
from app.models.membership import Membership
from app.models.user import User
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


def test_add_employee_creates_a_pending_seat_and_no_membership_yet(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    _seed_user(db_session, "employee-1", "employee@shopa.example")

    seat, checkout_url = add_employee(
        db_session,
        business_id=business_id,
        business_email="owner@shopa.example",
        invited_by_user_id="owner-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role="staff",
    )

    assert seat.status == "pending_payment"
    assert "checkout.stripe.com" in checkout_url
    membership = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership is None  # not granted until the webhook confirms payment


def test_a_third_employee_is_rejected(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    for i in range(MAX_EMPLOYEE_SEATS_PER_BUSINESS):
        _seed_user(db_session, f"employee-{i}", f"employee{i}@shopa.example")
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

    _seed_user(db_session, "employee-extra", "extra@shopa.example")
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


def test_rejects_an_email_with_no_existing_account(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")

    with pytest.raises(NoAccountForEmail):
        add_employee(
            db_session,
            business_id=business_id,
            business_email="owner@shopa.example",
            invited_by_user_id="owner-1",
            first_name="Nobody",
            surname="Yet",
            email="never-signed-up@shopa.example",
            role="staff",
        )


def test_rejects_re_inviting_an_already_reserved_email(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    _seed_user(db_session, "employee-1", "employee@shopa.example")
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
    _seed_user(db_session, "employee-1", "employee@shopa.example")

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
