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
    import json

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


def _fire_active_webhook(client, monkeypatch, business_id, seat_id, event_id="evt_isolation_active"):
    session = client._SessionLocal()
    event = {
        "id": event_id,
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": f"sub_{event_id}",
                "customer": f"cus_{event_id}",
                "status": "active",
                "items": {"data": []},
                "metadata": {"business_id": business_id, "employee_seat_id": seat_id},
            }
        },
    }
    monkeypatch.setattr(billing_client, "construct_webhook_event", lambda payload, sig: event)
    handle_webhook_event(session, b"{}", "sig")
    session.close()


def test_owner_can_add_an_employee_with_no_existing_account(client):
    # Direct product-direction change: no "sign up first" requirement.
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "never-signed-up@example.com", "role": "staff"},
        headers=headers_owner,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["employee_seat"]["status"] == "pending_payment"
    assert body["employee_seat"]["account_linked"] is False
    assert "checkout.stripe.com" in body["checkout_url"]


def test_a_non_owner_cannot_add_or_edit_an_employee(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="manager"))
    session.commit()
    session.close()

    response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Cian", "surname": "Walsh", "email": "cian@example.com", "role": "staff"},
        headers=headers_staff,
    )
    assert response.status_code == 403

    seat_id = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Cian", "surname": "Walsh", "email": "cian@example.com", "role": "staff"},
        headers=headers_owner,
    ).json()["employee_seat"]["id"]

    edit_response = client.patch(
        f"/businesses/{business['id']}/employee-seats/{seat_id}",
        json={"first_name": "Changed", "surname": "Walsh", "role": "staff"},
        headers=headers_staff,
    )
    assert edit_response.status_code == 403


def test_a_third_employee_is_rejected_via_the_api(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    for letter in ("b", "c"):
        response = client.post(
            f"/businesses/{business['id']}/employee-seats",
            json={"first_name": "E", "surname": letter, "email": f"{letter}@example.com", "role": "staff"},
            headers=headers_owner,
        )
        assert response.status_code == 201

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


def test_pending_employee_cannot_access_protected_routes_until_both_signup_and_payment(client, monkeypatch):
    monkeypatch.setattr(ai_client, "chat_completion", _fake_chat_completion)
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_employee = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    # Added with no existing account — the owner never needs to know
    # whether "b@example.com" has signed up yet.
    create_response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    )
    seat_id = create_response.json()["employee_seat"]["id"]

    # The employee hasn't even logged in yet — every protected route
    # must deny them (no membership can exist: get_current_membership
    # denies before any route body runs).
    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code == 403 for status_code in statuses.values()), statuses

    # Payment succeeds before the employee ever logs in — still no
    # access, since nobody's linked to the seat yet.
    _fire_active_webhook(client, monkeypatch, business["id"], seat_id)
    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code == 403 for status_code in statuses.values()), statuses

    seat_after_payment = client.get(f"/businesses/{business['id']}/employee-seats", headers=headers_owner).json()[0]
    assert seat_after_payment["status"] == "active"
    assert seat_after_payment["account_linked"] is False

    # The employee finally logs in — any authenticated request reconciles
    # them (app/security/auth.py::get_current_user_synced), and since
    # payment already succeeded, access activates immediately.
    client.get("/businesses", headers=headers_employee)

    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code != 403 for status_code in statuses.values()), statuses

    seat_after_login = client.get(f"/businesses/{business['id']}/employee-seats", headers=headers_owner).json()[0]
    assert seat_after_login["account_linked"] is True


def test_signup_before_payment_also_activates_once_payment_succeeds(client, monkeypatch):
    # The other ordering: the employee signs up/logs in first (so the
    # seat gets linked immediately at creation time), and access only
    # activates once payment succeeds afterward.
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_employee = bearer_header("user-b", "b@example.com")
    client.get("/businesses", headers=headers_employee)  # employee already has an account
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    create_response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    )
    seat = create_response.json()["employee_seat"]
    assert seat["account_linked"] is True  # linked immediately — the account already existed

    # Still no access — payment hasn't succeeded yet.
    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code == 403 for status_code in statuses.values()), statuses

    _fire_active_webhook(client, monkeypatch, business["id"], seat["id"])

    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code != 403 for status_code in statuses.values()), statuses


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

    _fire_active_webhook(client, monkeypatch, business["id"], seat_id, event_id="evt_idem_a")
    _fire_active_webhook(client, monkeypatch, business["id"], seat_id, event_id="evt_idem_b")

    session = client._SessionLocal()
    memberships = (
        session.query(Membership)
        .filter(Membership.business_id == uuid.UUID(business["id"]), Membership.user_id == "user-b")
        .all()
    )
    session.close()
    assert len(memberships) == 1


def test_owner_can_edit_an_employee_profile(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    seat_id = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    ).json()["employee_seat"]["id"]

    response = client.patch(
        f"/businesses/{business['id']}/employee-seats/{seat_id}",
        json={
            "first_name": "Beatrice",
            "surname": "O'Brien-Walsh",
            "role": "manager",
            "address_line1": "1 Grafton Street",
            "city": "Dublin",
            "postal_code": "D02",
            "country": "Ireland",
        },
        headers=headers_owner,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Beatrice"
    assert body["surname"] == "O'Brien-Walsh"
    assert body["role"] == "manager"
    assert body["address_line1"] == "1 Grafton Street"

    listed = client.get(f"/businesses/{business['id']}/employee-seats", headers=headers_owner).json()
    assert listed[0]["first_name"] == "Beatrice"


def test_list_shows_role_for_each_attached_employee(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "manager"},
        headers=headers_owner,
    )
    client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Cian", "surname": "Walsh", "email": "c@example.com", "role": "staff"},
        headers=headers_owner,
    )

    listed = client.get(f"/businesses/{business['id']}/employee-seats", headers=headers_owner).json()
    roles_by_name = {row["first_name"]: row["role"] for row in listed}
    assert roles_by_name == {"Bea": "manager", "Cian": "staff"}


# --- GET /businesses/{id}/members --------------------------------------------


def test_members_list_shows_the_owner_and_every_employee_with_role(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    client.patch(
        f"/businesses/{business['id']}",
        json={"manager_first_name": "Mauricio", "manager_surname": "Ruiz"},
        headers=headers_owner,
    )
    client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Antonio", "surname": "Ruiz", "email": "antonio@example.com", "role": "manager"},
        headers=headers_owner,
    )

    members = client.get(f"/businesses/{business['id']}/members", headers=headers_owner).json()
    by_role = {m["role"]: (m["first_name"], m["surname"]) for m in members}
    assert by_role["owner"] == ("Mauricio", "Ruiz")
    assert by_role["manager"] == ("Antonio", "Ruiz")
    owner_row = next(m for m in members if m["role"] == "owner")
    assert owner_row["employee_seat_id"] is None
    assert owner_row["account_linked"] is True
    manager_row = next(m for m in members if m["role"] == "manager")
    assert manager_row["employee_seat_id"] is not None
    # No email on this display-only route — that stays on the owner-only
    # .../employee-seats management route.
    assert "email" not in manager_row


def test_members_list_is_visible_to_a_non_owner_member(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_manager = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="manager"))
    session.commit()
    session.close()

    response = client.get(f"/businesses/{business['id']}/members", headers=headers_manager)
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_members_list_cannot_be_read_cross_tenant(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()

    response = client.get(f"/businesses/{business_b['id']}/members", headers=headers_a)
    assert response.status_code == 403


# --- DELETE /businesses/{id}/employee-seats/{seat_id} ------------------------


def test_owner_can_delete_an_employee(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    seat_id = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    ).json()["employee_seat"]["id"]

    response = client.delete(f"/businesses/{business['id']}/employee-seats/{seat_id}", headers=headers_owner)
    assert response.status_code == 204

    listed = client.get(f"/businesses/{business['id']}/employee-seats", headers=headers_owner).json()
    assert listed[0]["status"] == "canceled"


def test_a_non_owner_cannot_delete_an_employee(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_manager = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    seat_id = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b-target@example.com", "role": "staff"},
        headers=headers_owner,
    ).json()["employee_seat"]["id"]

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="manager"))
    session.commit()
    session.close()

    response = client.delete(
        f"/businesses/{business['id']}/employee-seats/{seat_id}", headers=headers_manager
    )
    assert response.status_code == 403


def test_deleting_an_active_employee_revokes_their_access(client, monkeypatch):
    monkeypatch.setattr(ai_client, "chat_completion", _fake_chat_completion)
    monkeypatch.setattr(billing_client, "cancel_subscription", lambda stripe_subscription_id: None)
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_employee = bearer_header("user-b", "b@example.com")
    client.get("/businesses", headers=headers_employee)
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    seat_id = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_owner,
    ).json()["employee_seat"]["id"]
    _fire_active_webhook(client, monkeypatch, business["id"], seat_id, event_id="evt_delete_active")

    # Confirmed access before deletion.
    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code != 403 for status_code in statuses.values()), statuses

    delete_response = client.delete(
        f"/businesses/{business['id']}/employee-seats/{seat_id}", headers=headers_owner
    )
    assert delete_response.status_code == 204

    statuses = _protected_route_statuses(client, business["id"], headers_employee)
    assert all(status_code == 403 for status_code in statuses.values()), statuses


def test_deleting_an_employee_cannot_cross_businesses(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b_owner = bearer_header("user-b-owner", "b-owner@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b_owner).json()
    seat_id = client.post(
        f"/businesses/{business_b['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "b@example.com", "role": "staff"},
        headers=headers_b_owner,
    ).json()["employee_seat"]["id"]

    # Business A's owner has no membership on B, so can't even attempt it.
    response = client.delete(f"/businesses/{business_b['id']}/employee-seats/{seat_id}", headers=headers_a)
    assert response.status_code == 403

    # B's own seat is untouched.
    still_there = client.get(f"/businesses/{business_b['id']}/employee-seats", headers=headers_b_owner).json()
    assert still_there[0]["status"] == "pending_payment"
