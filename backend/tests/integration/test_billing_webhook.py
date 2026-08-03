from datetime import datetime, timezone

import pytest

from app.billing import client, service
from app.billing.exceptions import InvalidWebhookSignature
from app.repositories.subscription import ProcessedStripeEventRepository, SubscriptionRepository


def _fake_event(event_id: str, event_type: str, obj: dict) -> dict:
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def test_checkout_session_completed_creates_subscription(db_session, business_id, monkeypatch):
    event = _fake_event(
        "evt_checkout_1",
        "checkout.session.completed",
        {"customer": "cus_123", "metadata": {"business_id": str(business_id)}},
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")

    subscription = SubscriptionRepository(db_session).get_by_business_id(business_id)
    assert subscription is not None
    assert subscription.stripe_customer_id == "cus_123"
    assert subscription.status == "incomplete"


def test_subscription_updated_syncs_status_and_period_end(db_session, business_id, monkeypatch):
    SubscriptionRepository(db_session).create(business_id=business_id, stripe_customer_id="cus_456")
    db_session.commit()

    period_end = datetime(2026, 9, 1, tzinfo=timezone.utc)
    event = _fake_event(
        "evt_sub_updated_1",
        "customer.subscription.updated",
        {
            "id": "sub_456",
            "customer": "cus_456",
            "status": "active",
            "items": {"data": [{"current_period_end": int(period_end.timestamp())}]},
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")

    subscription = SubscriptionRepository(db_session).get_by_stripe_customer_id("cus_456")
    assert subscription.status == "active"
    assert subscription.stripe_subscription_id == "sub_456"
    # SQLite (this test's DB) drops tzinfo on read-back, unlike the Postgres
    # this app actually runs on — normalize before comparing.
    stored_period_end = subscription.current_period_end.replace(tzinfo=timezone.utc)
    assert stored_period_end == period_end


def test_subscription_created_before_checkout_completed_creates_subscription(
    db_session, business_id, monkeypatch
):
    # Stripe does not guarantee webhook delivery order; this event has been
    # observed arriving before checkout.session.completed for the same
    # purchase.
    event = _fake_event(
        "evt_sub_created_1",
        "customer.subscription.created",
        {
            "id": "sub_early",
            "customer": "cus_early",
            "status": "active",
            "items": {"data": []},
            "metadata": {"business_id": str(business_id)},
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")

    subscription = SubscriptionRepository(db_session).get_by_stripe_customer_id("cus_early")
    assert subscription is not None
    assert subscription.business_id == business_id
    assert subscription.status == "active"
    assert subscription.stripe_subscription_id == "sub_early"


def test_payment_failure_marks_past_due(db_session, business_id, monkeypatch):
    SubscriptionRepository(db_session).create(business_id=business_id, stripe_customer_id="cus_789")
    db_session.commit()

    event = _fake_event(
        "evt_invoice_failed_1",
        "invoice.payment_failed",
        {
            "customer": "cus_789",
            "lines": {"data": []},
            "parent": {
                "subscription_details": {
                    "subscription": "sub_789",
                    "metadata": {"business_id": str(business_id)},
                }
            },
        },
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")

    subscription = SubscriptionRepository(db_session).get_by_stripe_customer_id("cus_789")
    assert subscription.status == "past_due"


def test_duplicate_event_id_is_not_reapplied(db_session, business_id, monkeypatch):
    event = _fake_event(
        "evt_dup_1",
        "checkout.session.completed",
        {"customer": "cus_dup", "metadata": {"business_id": str(business_id)}},
    )
    monkeypatch.setattr(client, "construct_webhook_event", lambda payload, sig: event)

    service.handle_webhook_event(db_session, b"{}", "sig")
    service.handle_webhook_event(db_session, b"{}", "sig")  # simulates a Stripe retry

    assert ProcessedStripeEventRepository(db_session).already_processed("evt_dup_1")
    subscription = SubscriptionRepository(db_session).get_by_business_id(business_id)
    assert subscription is not None


def test_invalid_signature_is_rejected(db_session, monkeypatch):
    def _raise(payload, sig):
        raise InvalidWebhookSignature("bad signature")

    monkeypatch.setattr(client, "construct_webhook_event", _raise)

    with pytest.raises(InvalidWebhookSignature):
        service.handle_webhook_event(db_session, b"{}", "bad-sig")
