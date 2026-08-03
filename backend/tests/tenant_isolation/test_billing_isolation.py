import uuid
from types import SimpleNamespace

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.billing import client
from app.billing.access import require_active_subscription
from app.main import app
from app.models import Base
from app.models.membership import Membership
from app.repositories.subscription import SubscriptionRepository
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client_and_session(tmp_path, monkeypatch):
    """Same pattern as test_business_isolation.py: a fresh isolated database
    per test, wired into the real app via dependency override.
    """
    patch_jwks(monkeypatch)
    db_path = tmp_path / "billing_isolation_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/__test_paid_only__/{business_id}")
    def _paid_only_probe(
        business_id: uuid.UUID, membership: Membership = Depends(require_active_subscription)
    ) -> dict:
        return {"business_id": str(membership.business_id)}

    yield TestClient(app), TestSessionLocal
    app.dependency_overrides.clear()
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/__test_paid_only__/{business_id}"]


def test_checkout_session_requires_auth(client_and_session):
    test_client, _ = client_and_session
    business_id = test_client.post(
        "/businesses", json={"name": "Shop A"}, headers=bearer_header("user-a", "a@example.com")
    ).json()["id"]

    response = test_client.post(f"/businesses/{business_id}/billing/checkout-session")
    assert response.status_code == 401


def test_checkout_session_rejects_non_member(client_and_session, monkeypatch):
    test_client, _ = client_and_session
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()["id"]

    response = test_client.post(f"/businesses/{business_id}/billing/checkout-session", headers=headers_b)
    assert response.status_code == 403


def test_checkout_session_uses_verified_email_not_client_input(client_and_session, monkeypatch):
    test_client, _ = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()["id"]

    captured = {}

    def fake_create_checkout_session(*, business_id, business_email, success_url, cancel_url):
        captured["business_email"] = business_email
        return SimpleNamespace(url="https://checkout.stripe.com/fake")

    monkeypatch.setattr(client, "create_checkout_session", fake_create_checkout_session)

    response = test_client.post(f"/businesses/{business_id}/billing/checkout-session", headers=headers)
    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.stripe.com/fake"
    # The email comes from the verified JWT, never anything the client could pass in the body.
    assert captured["business_email"] == "a@example.com"


def test_portal_session_404s_without_a_subscription(client_and_session):
    test_client, _ = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()["id"]

    response = test_client.post(f"/businesses/{business_id}/billing/portal-session", headers=headers)
    assert response.status_code == 404


def test_portal_session_rejects_cross_tenant_access(client_and_session):
    test_client, TestSessionLocal = client_and_session
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()["id"]

    db = TestSessionLocal()
    SubscriptionRepository(db).create(business_id=uuid.UUID(business_id), stripe_customer_id="cus_a")
    db.commit()
    db.close()

    # User B has no membership on business A, so this must 403 before it
    # ever reaches business A's subscription/Stripe customer.
    response = test_client.post(f"/businesses/{business_id}/billing/portal-session", headers=headers_b)
    assert response.status_code == 403


def test_subscription_status_reflects_none_then_active(client_and_session):
    test_client, TestSessionLocal = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()["id"]

    unsubscribed = test_client.get(f"/businesses/{business_id}/billing/subscription", headers=headers)
    assert unsubscribed.status_code == 200
    assert unsubscribed.json()["status"] is None

    db = TestSessionLocal()
    sub = SubscriptionRepository(db).create(business_id=uuid.UUID(business_id), stripe_customer_id="cus_a")
    sub.status = "active"
    db.commit()
    db.close()

    subscribed = test_client.get(f"/businesses/{business_id}/billing/subscription", headers=headers)
    assert subscribed.status_code == 200
    assert subscribed.json()["status"] == "active"


def test_require_active_subscription_gate(client_and_session):
    test_client, TestSessionLocal = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()["id"]

    # No subscription row at all.
    assert test_client.get(f"/__test_paid_only__/{business_id}", headers=headers).status_code == 402

    db = TestSessionLocal()
    sub = SubscriptionRepository(db).create(business_id=uuid.UUID(business_id), stripe_customer_id="cus_a")
    db.commit()
    db.close()

    # Row exists but not active yet (e.g. "incomplete").
    assert test_client.get(f"/__test_paid_only__/{business_id}", headers=headers).status_code == 402

    db = TestSessionLocal()
    sub = SubscriptionRepository(db).get_by_business_id(uuid.UUID(business_id))
    sub.status = "active"
    db.commit()
    db.close()

    assert test_client.get(f"/__test_paid_only__/{business_id}", headers=headers).status_code == 200
