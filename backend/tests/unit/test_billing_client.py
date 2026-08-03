import hashlib
import hmac
import json
import time
import uuid

import pytest
import stripe

from app.billing import client
from app.billing.exceptions import InvalidWebhookSignature
from app.settings.config import get_settings


def _signed_payload(secret: str, payload: dict) -> tuple[bytes, str]:
    payload_bytes = json.dumps(payload).encode()
    timestamp = int(time.time())
    signed = f"{timestamp}.{payload_bytes.decode()}".encode()
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return payload_bytes, f"t={timestamp},v1={signature}"


@pytest.fixture(autouse=True)
def _stripe_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_dummy")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_test_123")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fake_event_payload(event_id: str, event_type: str) -> dict:
    return {
        "id": event_id,
        "object": "event",
        "type": event_type,
        "data": {"object": {}},
    }


def test_construct_webhook_event_accepts_a_correctly_signed_payload():
    payload, signature_header = _signed_payload(
        "whsec_test_dummy", _fake_event_payload("evt_1", "ping")
    )
    event = client.construct_webhook_event(payload, signature_header)
    assert event["id"] == "evt_1"


def test_construct_webhook_event_rejects_a_bad_signature():
    payload, _ = _signed_payload("whsec_test_dummy", _fake_event_payload("evt_1", "ping"))
    with pytest.raises(InvalidWebhookSignature):
        client.construct_webhook_event(payload, "t=123,v1=deadbeef")


def test_create_checkout_session_offers_card_and_sepa_debit(monkeypatch):
    captured = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return type("FakeSession", (), {"url": "https://checkout.stripe.com/test"})()

    monkeypatch.setattr(stripe.checkout.Session, "create", _fake_create)

    session = client.create_checkout_session(
        business_id=uuid.uuid4(),
        business_email="owner@example.com",
        success_url="https://app.example.com/success",
        cancel_url="https://app.example.com/cancel",
    )

    assert session.url == "https://checkout.stripe.com/test"
    assert captured["mode"] == "subscription"
    assert captured["payment_method_types"] == ["card", "sepa_debit"]
    assert captured["automatic_tax"] == {"enabled": True}
    assert captured["line_items"] == [{"price": "price_test_123", "quantity": 1}]
