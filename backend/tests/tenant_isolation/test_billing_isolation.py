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

    def fake_create_checkout_session(
        *, business_id, business_email, success_url, cancel_url, price_id, existing_stripe_customer_id=None
    ):
        captured["business_email"] = business_email
        return SimpleNamespace(url="https://checkout.stripe.com/fake")

    monkeypatch.setattr(client, "create_checkout_session", fake_create_checkout_session)

    response = test_client.post(f"/businesses/{business_id}/billing/checkout-session", headers=headers)
    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.stripe.com/fake"
    # The email comes from the verified JWT, never anything the client could pass in the body.
    assert captured["business_email"] == "a@example.com"


def test_checkout_session_reuses_existing_stripe_customer_on_resubscribe(client_and_session, monkeypatch):
    # Regression test: resubscribing (e.g. after a cancellation) used to
    # mint a brand new Stripe Customer every time, which produced a second
    # subscriptions row for the same business — violating the one-row-per-
    # business invariant and leaving orphaned duplicate Customers in Stripe.
    test_client, TestSessionLocal = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()["id"]

    db = TestSessionLocal()
    SubscriptionRepository(db).create(business_id=uuid.UUID(business_id), stripe_customer_id="cus_existing")
    db.commit()
    db.close()

    captured = {}

    def fake_create_checkout_session(
        *, business_id, business_email, success_url, cancel_url, price_id, existing_stripe_customer_id=None
    ):
        captured["existing_stripe_customer_id"] = existing_stripe_customer_id
        return SimpleNamespace(url="https://checkout.stripe.com/fake")

    monkeypatch.setattr(client, "create_checkout_session", fake_create_checkout_session)
    response = test_client.post(f"/businesses/{business_id}/billing/checkout-session", headers=headers)

    assert response.status_code == 200
    assert captured["existing_stripe_customer_id"] == "cus_existing"


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


# --- branch billing: separate subscription at the discounted price -------
# A branch (Business.parent_business_id set) gets its own Subscription
# row, same as any standalone business — the only difference is which
# Stripe price checkout charges. app/billing/service.py::start_checkout
# is the one place that decision is made.


def test_checkout_uses_the_standard_price_for_a_standalone_business(client_and_session, monkeypatch):
    test_client, _ = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    business_id = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()["id"]

    captured = {}

    def fake_create_checkout_session(
        *, business_id, business_email, success_url, cancel_url, price_id, existing_stripe_customer_id=None
    ):
        captured["price_id"] = price_id
        return SimpleNamespace(url="https://checkout.stripe.com/fake")

    monkeypatch.setattr(client, "create_checkout_session", fake_create_checkout_session)
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_standard")
    monkeypatch.setenv("STRIPE_BRANCH_PRICE_ID", "price_branch")
    from app.settings.config import get_settings

    get_settings.cache_clear()

    response = test_client.post(f"/businesses/{business_id}/billing/checkout-session", headers=headers)
    assert response.status_code == 200
    assert captured["price_id"] == "price_standard"
    get_settings.cache_clear()


def test_checkout_uses_the_discounted_branch_price_for_a_branch(client_and_session, monkeypatch):
    test_client, _ = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    primary_id = test_client.post("/businesses", json={"name": "Text Bike Shop"}, headers=headers).json()["id"]
    branch = test_client.post(f"/businesses/{primary_id}/branches", json={"name": "Test Shop"}, headers=headers)
    assert branch.status_code == 201
    branch_id = branch.json()["id"]

    captured = {}

    def fake_create_checkout_session(
        *, business_id, business_email, success_url, cancel_url, price_id, existing_stripe_customer_id=None
    ):
        captured["price_id"] = price_id
        return SimpleNamespace(url="https://checkout.stripe.com/fake")

    monkeypatch.setattr(client, "create_checkout_session", fake_create_checkout_session)
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_standard")
    monkeypatch.setenv("STRIPE_BRANCH_PRICE_ID", "price_branch")
    from app.settings.config import get_settings

    get_settings.cache_clear()

    response = test_client.post(f"/businesses/{branch_id}/billing/checkout-session", headers=headers)
    assert response.status_code == 200
    assert captured["price_id"] == "price_branch"
    get_settings.cache_clear()


# --- POST /businesses/{id}/branches ---------------------------------------


def test_owner_can_add_a_branch(client_and_session):
    test_client, _ = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    primary_id = test_client.post("/businesses", json={"name": "Text Bike Shop"}, headers=headers).json()["id"]

    response = test_client.post(f"/businesses/{primary_id}/branches", json={"name": "Test Shop"}, headers=headers)
    assert response.status_code == 201
    assert response.json()["parent_business_id"] == primary_id


def test_adding_a_branch_does_not_block_the_owner_from_ever_having_created_their_primary_shop(client_and_session):
    # The real end-to-end scenario this feature exists for: one owner,
    # one standalone shop, one branch under it — a POST /businesses for
    # a *second standalone* shop must still be rejected, but the branch
    # itself must never have been blocked by that same limit.
    test_client, _ = client_and_session
    headers = bearer_header("user-a", "a@example.com")
    primary_id = test_client.post("/businesses", json={"name": "Text Bike Shop"}, headers=headers).json()["id"]
    test_client.post(f"/businesses/{primary_id}/branches", json={"name": "Test Shop"}, headers=headers)

    second_standalone = test_client.post("/businesses", json={"name": "Another Shop"}, headers=headers)
    assert second_standalone.status_code == 409

    listing = test_client.get("/businesses", headers=headers).json()
    assert len(listing) == 2


def test_a_non_owner_cannot_add_a_branch(client_and_session):
    test_client, _ = client_and_session
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_other = bearer_header("user-b", "b@example.com")
    primary_id = test_client.post("/businesses", json={"name": "Text Bike Shop"}, headers=headers_owner).json()["id"]

    response = test_client.post(
        f"/businesses/{primary_id}/branches", json={"name": "Test Shop"}, headers=headers_other
    )
    assert response.status_code == 403


def test_cannot_add_a_branch_to_a_business_you_are_not_a_member_of(client_and_session):
    """The core tenant-isolation guarantee (PR-6.1/6.2, ED-008) extended to
    branch creation: a stranger can't add a branch under a business they
    have no membership in at all, even by guessing a real id.
    """
    test_client, _ = client_and_session
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = test_client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()["id"]

    response = test_client.post(f"/businesses/{business_a}/branches", json={"name": "Branch"}, headers=headers_b)
    assert response.status_code == 403
