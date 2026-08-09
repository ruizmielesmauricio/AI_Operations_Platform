import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai import client as ai_client
from app.api.deps import get_db
from app.billing import client as billing_client
from app.billing.service import handle_webhook_event
from app.main import app
from app.models import Base
from app.models.membership import Membership
from app.settings.config import get_settings
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    monkeypatch.setenv("STRIPE_EMPLOYEE_SEAT_PRICE_ID", "price_employee_seat")
    get_settings.cache_clear()

    db_path = tmp_path / "employee_seat_isolation_test.db"
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
        return SimpleNamespace(
            url=f"https://checkout.stripe.com/fake?seat={(extra_metadata or {}).get('employee_seat_id')}"
        )

    monkeypatch.setattr(billing_client, "create_checkout_session", fake_create_checkout_session)

    test_client = TestClient(app)
    test_client._SessionLocal = TestSessionLocal
    yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
    if response_format is not None:
        content = json.dumps({"intent": "financial_performance", "period": "default_recent", "metric": None})
    else:
        content = "No data yet."
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
        "model": "test-model",
    }


def _protected_route_statuses(client, business_id, headers):
    return {
        "dashboard": client.get(f"/businesses/{business_id}/analytics/financial-performance", headers=headers).status_code,
        "uploads": client.get(f"/businesses/{business_id}/uploads", headers=headers).status_code,
        "reports": client.get(f"/businesses/{business_id}/reports", headers=headers).status_code,
        "ask_orla": client.post(
            f"/businesses/{business_id}/ai/chat", json={"question": "How's revenue?"}, headers=headers
        ).status_code,
    }


def test_owner_can_start_the_add_employee_flow(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_employee = bearer_header("user-b", "b@example.com")
    client.get("/businesses", headers=headers_employee)  # seeds the employee's own User row
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["employee_seat"]["status"] == "pending_payment"
    assert "checkout.stripe.com" in body["checkout_url"]


def test_a_non_owner_cannot_add_an_employee(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    headers_new_hire = bearer_header("user-c", "c@example.com")
    client.get("/businesses", headers=headers_new_hire)
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="manager"))
    session.commit()
    session.close()

    response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Cian", "surname": "Walsh", "email": "c@example.com", "role": "staff"},
        headers=headers_staff,
    )
    assert response.status_code == 403


def test_a_third_employee_is_rejected_via_the_api(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    for letter in ("b", "c"):
        client.get("/businesses", headers=bearer_header(f"user-{letter}", f"{letter}@example.com"))
        response = client.post(
            f"/businesses/{business['id']}/employee-seats",
            json={"first_name": "E", "surname": letter, "email": f"{letter}@example.com", "role": "staff"},
            headers=headers_owner,
        )
        assert response.status_code == 201

    client.get("/businesses", headers=bearer_header("user-d", "d@example.com"))
    third = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "E", "surname": "d", "email": "d@example.com", "role": "staff"},
        headers=headers_owner,
    )
    assert third.status_code == 409


def test_employee_actions_cannot_cross_businesses(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b_owner = bearer_header("user-b-owner", "b-owner@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b_owner).json()

    # Business A's owner has no membership on B at all.
    response = client.get(f"/businesses/{business_b['id']}/employee-seats", headers=headers_a)
    assert response.status_code == 403
    response = client.post(
        f"/businesses/{business_b['id']}/employee-seats",
        json={"first_name": "X", "surname": "Y", "email": "a@example.com", "role": "staff"},
        headers=headers_a,
    )
    assert response.status_code == 403

    # A's own list never contains B's seats, and vice versa — proven by
    # each staying empty (neither business added any seat yet).
    assert client.get(f"/businesses/{business_a['id']}/employee-seats", headers=headers_a).json() == []
    assert client.get(f"/businesses/{business_b['id']}/employee-seats", headers=headers_b_owner).json() == []


def test_pending_employee_cannot_access_protected_routes_until_payment_confirms(client, monkeypatch):
    monkeypatch.setattr(ai_client, "chat_completion", _fake_chat_completion)
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_employee = bearer_header("user-b", "b@example.com")
    client.get("/businesses", headers=headers_employee)
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    create_response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    )
    seat_id = create_response.json()["employee_seat"]["id"]

    # Not paid yet — every protected route must deny the employee.
    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code == 403 for status_code in statuses.values()), statuses

    # Confirm payment via the webhook (mirrors Stripe's real callback).
    session = client._SessionLocal()
    event = {
        "id": "evt_isolation_active",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_isolation_1",
                "customer": "cus_isolation_1",
                "status": "active",
                "items": {"data": []},
                "metadata": {"business_id": business["id"], "employee_seat_id": seat_id},
            }
        },
    }
    monkeypatch.setattr(billing_client, "construct_webhook_event", lambda payload, sig: event)
    handle_webhook_event(session, b"{}", "sig")
    session.close()

    # Now paid — every protected route must allow the employee, per
    # existing get_current_membership auth patterns (role isn't checked
    # further on these particular routes today).
    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code != 403 for status_code in statuses.values()), statuses

    seats = client.get(f"/businesses/{business['id']}/employee-seats", headers=headers_owner).json()
    assert seats[0]["status"] == "active"


def test_activation_via_webhook_is_idempotent(client, monkeypatch):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_employee = bearer_header("user-b", "b@example.com")
    client.get("/businesses", headers=headers_employee)
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    seat_id = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    ).json()["employee_seat"]["id"]

    def _event(event_id):
        return {
            "id": event_id,
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_idem_1",
                    "customer": "cus_idem_1",
                    "status": "active",
                    "items": {"data": []},
                    "metadata": {"business_id": business["id"], "employee_seat_id": seat_id},
                }
            },
        }

    session = client._SessionLocal()
    monkeypatch.setattr(billing_client, "construct_webhook_event", lambda payload, sig: _event("evt_idem_a"))
    handle_webhook_event(session, b"{}", "sig")
    monkeypatch.setattr(billing_client, "construct_webhook_event", lambda payload, sig: _event("evt_idem_b"))
    handle_webhook_event(session, b"{}", "sig")

    memberships = (
        session.query(Membership)
        .filter(Membership.business_id == uuid.UUID(business["id"]), Membership.user_id == "user-b")
        .all()
    )
    session.close()
    assert len(memberships) == 1
