"""Billing — €80/month Stripe subscription, test mode — AC-044..AC-049 (criteria §6).

AC-044 and AC-048 call the real Stripe *test-mode* API. They need
STRIPE_SECRET_KEY=sk_test_... and the price ids (ORLA_STRIPE_PRICE_ID,
ORLA_STRIPE_BRANCH_PRICE_ID) in the environment or in .env.test.local.
Without them they fail (never skip), so the score stays honest.
"""

import hashlib
import hmac
import json
import os
import re
import time
import uuid

import pytest

from conftest import auth

WEBHOOK_SECRET = "whsec_acceptance_only_not_a_real_secret"


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _event(event_id: str, event_type: str, obj: dict) -> bytes:
    return json.dumps({"id": event_id, "object": "event", "type": event_type, "data": {"object": obj}}).encode()


def _post_webhook(orla, payload: bytes, signature: str | None = None):
    return orla.client.post("/billing/webhooks/stripe", content=payload,
                            headers={"stripe-signature": signature or _sign(payload),
                                     "content-type": "application/json"})


@pytest.fixture()
def webhook_secret(monkeypatch):
    from app.settings.config import get_settings

    monkeypatch.setattr(get_settings(), "stripe_webhook_secret", WEBHOOK_SECRET)


def _activate(orla, business_id: str, n: int = 1, status: str = "active", **meta):
    customer = f"cus_wh_{business_id[:8]}"
    metadata = {"business_id": business_id, **meta}
    r1 = _post_webhook(orla, _event(f"evt_cs_{business_id}_{n}", "checkout.session.completed",
                                    {"customer": customer, "metadata": metadata}))
    r2 = _post_webhook(orla, _event(f"evt_sub_{business_id}_{n}", "customer.subscription.updated", {
        "id": f"sub_wh_{business_id[:8]}", "customer": customer, "status": status,
        "items": {"data": [{"current_period_end": int(time.time()) + 30 * 86400}]}, "metadata": metadata,
    }))
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)


def _stripe_test_env(monkeypatch, price_env: str):
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    price = os.environ.get(price_env) or os.environ.get(price_env.replace("ORLA_", ""), "")
    if not key.startswith("sk_test_") or not price:
        pytest.fail(f"Needs STRIPE_SECRET_KEY=sk_test_... and {price_env} (Stripe sandbox) in the environment")
    from app.settings.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "stripe_secret_key", key)
    monkeypatch.setattr(s, "stripe_price_id", os.environ.get("ORLA_STRIPE_PRICE_ID", s.stripe_price_id))
    monkeypatch.setattr(s, "stripe_branch_price_id",
                        os.environ.get("ORLA_STRIPE_BRANCH_PRICE_ID", s.stripe_branch_price_id))
    import stripe

    stripe.api_key = key
    return stripe


def _session_from_url(stripe, url: str):
    match = re.search(r"(cs_test_[A-Za-z0-9]+)", url)
    assert match, f"not a Stripe test-mode checkout URL: {url}"
    return stripe.checkout.Session.retrieve(match.group(1), expand=["line_items.data.price"])


def _assert_price(session, amount: int):
    assert session.livemode is False
    assert session.mode == "subscription"
    assert list(session.payment_method_types) == ["card", "sepa_debit"], (
        f"checkout must offer card first and SEPA second, got {session.payment_method_types}")
    assert session.automatic_tax.enabled is True
    price = session.line_items.data[0].price
    assert (price.unit_amount, price.currency) == (amount, "eur")
    assert price.recurring.interval == "month" and price.recurring.interval_count == 1
    assert price.tax_behavior == "exclusive", "prices are advertised excluding VAT"


def test_checkout_80_eur_card_and_sepa(orla, monkeypatch):
    """AC-044: €80/month (excl. VAT), card then SEPA, Stripe Tax on, test mode."""
    stripe = _stripe_test_env(monkeypatch, "ORLA_STRIPE_PRICE_ID")
    biz = orla.create_business("pay-owner", subscribe=False)
    resp = orla.client.post(f"/businesses/{biz['id']}/billing/checkout-session", headers=auth("pay-owner"))
    assert resp.status_code == 200, resp.text
    _assert_price(_session_from_url(stripe, resp.json()["checkout_url"]), 8000)


def test_access_only_from_verified_webhook(orla, webhook_secret):
    """AC-045: paid access comes only from a signature-verified webhook."""
    biz = orla.create_business("wh-owner", subscribe=False)
    h = auth("wh-owner")
    gated = lambda: orla.client.post(f"/businesses/{biz['id']}/uploads",
                                     json={"filename": "s.csv", "entity_type": "sales"}, headers=h)
    assert gated().status_code == 402, "unpaid business could start an upload"

    forged = _event("evt_forged", "checkout.session.completed",
                    {"customer": "cus_x", "metadata": {"business_id": biz["id"]}})
    bad = _post_webhook(orla, forged, signature=_sign(forged, secret="whsec_wrong"))
    assert bad.status_code == 400
    assert gated().status_code == 402, "an unsigned/forged webhook granted access"

    _activate(orla, biz["id"])
    assert gated().status_code == 201, "a verified 'active' webhook did not grant access"


def test_webhook_idempotent(orla, webhook_secret):
    """AC-046: a replayed event is applied once (it can't undo a later change)."""
    biz = orla.create_business("idem-owner", subscribe=False)
    _activate(orla, biz["id"], n=1, status="active")
    canceled = _event("evt_cancel_1", "customer.subscription.updated", {
        "id": f"sub_wh_{biz['id'][:8]}", "customer": f"cus_wh_{biz['id'][:8]}", "status": "canceled",
        "items": {"data": [{"current_period_end": int(time.time())}]}, "metadata": {"business_id": biz["id"]},
    })
    assert _post_webhook(orla, canceled).status_code == 200
    replay = _event(f"evt_sub_{biz['id']}_1", "customer.subscription.updated", {
        "id": f"sub_wh_{biz['id'][:8]}", "customer": f"cus_wh_{biz['id'][:8]}", "status": "active",
        "items": {"data": [{"current_period_end": int(time.time()) + 30 * 86400}]},
        "metadata": {"business_id": biz["id"]},
    })
    assert _post_webhook(orla, replay).status_code == 200
    status = orla.client.get(f"/businesses/{biz['id']}/billing/subscription", headers=auth("idem-owner")).json()
    assert status["status"] == "canceled", "a replayed event re-activated a canceled subscription"


def test_customer_portal_owner_only(orla, monkeypatch):
    """AC-047: owner opens the Stripe Customer Portal; others are refused."""
    from app.billing import client as billing_client

    calls = []

    class _Portal:
        url = "https://billing.stripe.com/p/session/test_acceptance"

    def _portal(*args, **kwargs):
        calls.append(kwargs or args)
        return _Portal()

    monkeypatch.setattr(billing_client, "create_billing_portal_session", _portal)
    biz = orla.create_business("portal-owner")
    orla.add_member(biz["id"], "portal-manager", "manager")
    orla.add_member(biz["id"], "portal-staff", "staff")
    ok = orla.client.post(f"/businesses/{biz['id']}/billing/portal-session", headers=auth("portal-owner"))
    assert ok.status_code == 200 and ok.json()["portal_url"].startswith("https://billing.stripe.com/")
    for user in ("portal-manager", "portal-staff"):
        r = orla.client.post(f"/businesses/{biz['id']}/billing/portal-session", headers=auth(user))
        assert r.status_code == 403, f"{user} reached the billing portal"
    assert len(calls) == 1


def test_branch_addon_30_eur_separate_subscription(orla, monkeypatch, webhook_secret):
    """AC-048: a branch subscribes separately at €30/month (excl. VAT)."""
    stripe = _stripe_test_env(monkeypatch, "ORLA_STRIPE_BRANCH_PRICE_ID")
    parent = orla.create_business("branch-owner")
    resp = orla.client.post(f"/businesses/{parent['id']}/branches",
                            json={"name": "Second Shop", "template": "bicycle_shop", "timezone": "Europe/Dublin"},
                            headers=auth("branch-owner"))
    assert resp.status_code in (200, 201), resp.text
    branch = resp.json()
    co = orla.client.post(f"/businesses/{branch['id']}/billing/checkout-session", headers=auth("branch-owner"))
    assert co.status_code == 200, co.text
    _assert_price(_session_from_url(stripe, co.json()["checkout_url"]), 3000)

    _activate(orla, branch["id"])
    from app.models.subscription import Subscription

    with orla.session() as s:
        subs = {str(x.business_id): x for x in s.query(Subscription).all()}
    assert parent["id"] in subs and branch["id"] in subs
    assert subs[parent["id"]].stripe_subscription_id != subs[branch["id"]].stripe_subscription_id


def test_live_key_refused_outside_production(orla, monkeypatch):
    """AC-049: with a live key outside production, billing refuses to call
    Stripe at all."""
    import stripe

    from app.settings.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "environment", "local")
    monkeypatch.setattr(s, "stripe_secret_key", "sk_live_" + "x" * 24)
    monkeypatch.setattr(s, "stripe_price_id", "price_live_placeholder")
    called = []
    monkeypatch.setattr(stripe.checkout.Session, "create",
                        classmethod(lambda cls, *a, **k: called.append(k) or {"url": "https://x"}))
    biz = orla.create_business("live-owner", subscribe=False)
    try:
        resp = orla.client.post(f"/businesses/{biz['id']}/billing/checkout-session", headers=auth("live-owner"))
        status = resp.status_code
    except Exception:
        status = 500
    assert called == [], "a live Stripe key was used outside production"
    assert status >= 400
