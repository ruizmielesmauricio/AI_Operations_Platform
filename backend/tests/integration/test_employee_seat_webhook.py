import uuid

from app.billing import client, service
from app.models.audit_log import AuditLog
from app.models.membership import Membership
from app.models.user import User
from app.repositories.employee_seat import EmployeeSeatRepository


def _fake_event(event_id: str, event_type: str, obj: dict) -> dict:
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def _make_seat(db_session, business_id, *, role="staff"):
    owner = User(id="owner-1", email="owner@shopa.example")
    employee = User(id="employee-1", email="employee@shopa.example")
    db_session.add_all([owner, employee])
    db_session.commit()
    seat = EmployeeSeatRepository(db_session).create(
        business_id=business_id,
        invited_by_user_id="owner-1",
        user_id="employee-1",
        first_name="Aoife",
        surname="Byrne",
        email="employee@shopa.example",
        role=role,
    )
    db_session.commit()
    return seat


def test_checkout_completed_sets_customer_id_but_stays_pending(db_session, business_id, monkeypatch):
    seat = _make_seat(db_session, business_id)
    event = _fake_event(
        "evt_seat_checkout_1",
        "checkout.session.completed",
        {
            "customer": "cus_seat_1",
            "metadata": {"business_id": str(business_id), "employee_seat_id": str(seat.id)},
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")

    db_session.refresh(seat)
    assert seat.stripe_customer_id == "cus_seat_1"
    assert seat.status == "pending_payment"
    membership = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership is None


def test_subscription_active_activates_membership_with_the_invited_role(db_session, business_id, monkeypatch):
    seat = _make_seat(db_session, business_id, role="manager")
    event = _fake_event(
        "evt_seat_active_1",
        "customer.subscription.updated",
        {
            "id": "sub_seat_1",
            "customer": "cus_seat_1",
            "status": "active",
            "items": {"data": []},
            "metadata": {"business_id": str(business_id), "employee_seat_id": str(seat.id)},
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")

    db_session.refresh(seat)
    assert seat.status == "active"
    assert seat.stripe_subscription_id == "sub_seat_1"
    membership = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership is not None
    assert membership.role == "manager"
    activated = (
        db_session.query(AuditLog)
        .filter(AuditLog.business_id == business_id, AuditLog.action == "employee_membership_activated")
        .all()
    )
    assert len(activated) == 1


def test_activation_is_idempotent_across_repeated_active_events(db_session, business_id, monkeypatch):
    seat = _make_seat(db_session, business_id)

    def _event(event_id):
        return _fake_event(
            event_id,
            "customer.subscription.updated",
            {
                "id": "sub_seat_2",
                "customer": "cus_seat_2",
                "status": "active",
                "items": {"data": []},
                "metadata": {"business_id": str(business_id), "employee_seat_id": str(seat.id)},
            },
        )

    # Two distinct Stripe event ids (a real "updated" firing twice), not a
    # literal retry — ProcessedStripeEventRepository's own dedup only
    # catches an identical event id, so this specifically exercises
    # _apply_employee_seat_event's own idempotency, not that shortcut.
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: _event("evt_seat_active_a"))
    service.handle_webhook_event(db_session, b"{}", "sig")
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: _event("evt_seat_active_b"))
    service.handle_webhook_event(db_session, b"{}", "sig")

    memberships = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .all()
    )
    assert len(memberships) == 1
    activated = (
        db_session.query(AuditLog)
        .filter(AuditLog.business_id == business_id, AuditLog.action == "employee_membership_activated")
        .all()
    )
    assert len(activated) == 1  # not double-logged on the second identical transition


def test_payment_failure_before_ever_activating_creates_no_membership(db_session, business_id, monkeypatch):
    seat = _make_seat(db_session, business_id)
    event = _fake_event(
        "evt_seat_failed_1",
        "customer.subscription.updated",
        {
            "id": "sub_seat_3",
            "customer": "cus_seat_3",
            "status": "past_due",
            "items": {"data": []},
            "metadata": {"business_id": str(business_id), "employee_seat_id": str(seat.id)},
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")

    db_session.refresh(seat)
    assert seat.status == "payment_failed"
    membership = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership is None


def test_cancellation_after_activation_revokes_the_membership(db_session, business_id, monkeypatch):
    seat = _make_seat(db_session, business_id)
    active_event = _fake_event(
        "evt_seat_cancel_active",
        "customer.subscription.updated",
        {
            "id": "sub_seat_4",
            "customer": "cus_seat_4",
            "status": "active",
            "items": {"data": []},
            "metadata": {"business_id": str(business_id), "employee_seat_id": str(seat.id)},
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: active_event)
    service.handle_webhook_event(db_session, b"{}", "sig")

    membership_before = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership_before is not None

    deleted_event = _fake_event(
        "evt_seat_cancel_deleted",
        "customer.subscription.deleted",
        {
            "id": "sub_seat_4",
            "customer": "cus_seat_4",
            "status": "canceled",
            "items": {"data": []},
            "metadata": {"business_id": str(business_id), "employee_seat_id": str(seat.id)},
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: deleted_event)
    service.handle_webhook_event(db_session, b"{}", "sig")

    db_session.refresh(seat)
    assert seat.status == "canceled"
    membership_after = (
        db_session.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == "employee-1")
        .first()
    )
    assert membership_after is None
    canceled_logs = (
        db_session.query(AuditLog)
        .filter(AuditLog.business_id == business_id, AuditLog.action == "employee_payment_canceled")
        .all()
    )
    assert len(canceled_logs) == 1
