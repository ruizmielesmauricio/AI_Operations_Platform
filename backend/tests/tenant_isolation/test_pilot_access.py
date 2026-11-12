"""Free pilot access (decision 2026-11-12: pilot testers don't pay) and staff
invites that work without email delivery configured."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.application import employee_seats as employee_seats_module
from app.application.pilot_access import (
    PilotAccessError,
    end_pilot_access,
    find_owned_businesses,
    grant_pilot_access,
)
from app.billing import client as billing_client
from app.billing.pilot import pilot_access_active
from app.imports import r2_client
from app.main import app
from app.models import Base
from app.models.business import Business
from app.models.employee_seat import EmployeeSeat
from app.models.notification import Notification
from tests.auth_helpers import bearer_header, patch_jwks, seed_active_subscription

OWNER = ("pilot-owner", "owner@pilot.ie")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    monkeypatch.setattr(r2_client, "generate_upload_url", lambda *, storage_key: f"https://r2.test/{storage_key}")

    def no_stripe(**kwargs):
        raise AssertionError("Stripe must not be called for a pilot business")

    monkeypatch.setattr(billing_client, "create_checkout_session", no_stripe)
    engine = create_engine(f"sqlite:///{tmp_path / 'pilot.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    test_client._SessionLocal = SessionLocal
    test_client._engine = engine
    yield test_client
    app.dependency_overrides.clear()


def _headers():
    return bearer_header(*OWNER)


def _create_business(client, name="Pilot Shop"):
    return client.post("/businesses", json={"name": name}, headers=_headers()).json()


def _grant(client, business_id, days=90, now=None):
    with client._SessionLocal() as db:
        return grant_pilot_access(db, business_id=uuid.UUID(business_id), days=days, now=now)


def _request_upload(client, business_id):
    return client.post(
        f"/businesses/{business_id}/uploads",
        json={"filename": "sales.csv", "entity_type": "sales"},
        headers=_headers(),
    )


def test_pilot_business_can_upload_without_paying(client):
    business = _create_business(client)
    assert _request_upload(client, business["id"]).status_code == 402  # not a pilot yet

    _grant(client, business["id"])
    assert _request_upload(client, business["id"]).status_code == 201


def test_expired_pilot_needs_a_subscription_again(client):
    business = _create_business(client)
    _grant(client, business["id"], days=30, now=datetime.now(timezone.utc) - timedelta(days=31))
    assert _request_upload(client, business["id"]).status_code == 402


def test_ending_a_pilot_removes_access_and_tells_the_owner(client):
    business = _create_business(client)
    _grant(client, business["id"])
    with client._SessionLocal() as db:
        end_pilot_access(db, business_id=uuid.UUID(business["id"]))
    assert _request_upload(client, business["id"]).status_code == 402
    with client._SessionLocal() as db:
        titles = [n.title for n in db.scalars(select(Notification))]
    assert "Your pilot access has ended" in titles


def test_paid_subscription_still_works_and_wins_over_pilot(client):
    business = _create_business(client)
    seed_active_subscription(client._engine, business["id"])
    _grant(client, business["id"])
    status = client.get(f"/businesses/{business['id']}/billing/subscription", headers=_headers()).json()
    assert status["access"] == "subscription"


def test_billing_status_reports_pilot_access_and_end_date(client):
    business = _create_business(client)
    status = client.get(f"/businesses/{business['id']}/billing/subscription", headers=_headers()).json()
    assert status["access"] is None

    until = _grant(client, business["id"], days=90)
    status = client.get(f"/businesses/{business['id']}/billing/subscription", headers=_headers()).json()
    assert status["access"] == "pilot"
    assert status["status"] is None
    assert status["pilot_access_until"][:10] == until.date().isoformat()


def test_branch_added_during_a_pilot_is_free_for_the_same_window(client):
    business = _create_business(client)
    until = _grant(client, business["id"])
    branch = client.post(
        f"/businesses/{business['id']}/branches",
        json={"name": "Pilot Shop Cork", "timezone": "Europe/Dublin"},
        headers=_headers(),
    )
    assert branch.status_code == 201
    assert branch.json()["pilot_access_until"][:10] == until.date().isoformat()
    assert _request_upload(client, branch.json()["id"]).status_code == 201


def test_grant_covers_existing_branches(client):
    business = _create_business(client)
    seed_active_subscription(client._engine, business["id"])  # needed only to add a paid branch first
    branch = client.post(
        f"/businesses/{business['id']}/branches",
        json={"name": "Pilot Shop Galway", "timezone": "Europe/Dublin"},
        headers=_headers(),
    ).json()
    assert _request_upload(client, branch["id"]).status_code == 402
    _grant(client, business["id"])
    assert _request_upload(client, branch["id"]).status_code == 201


def test_staff_seat_added_during_a_pilot_is_active_without_checkout(client, monkeypatch):
    monkeypatch.setattr(employee_seats_module, "send_employee_invite_email", lambda **kwargs: False)
    business = _create_business(client)
    _grant(client, business["id"])
    response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Ann", "surname": "Staff", "email": "ann@pilot.ie", "role": "staff"},
        headers=_headers(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["checkout_url"] is None
    assert body["employee_seat"]["status"] == "active"
    assert body["invite_email_sent"] is False
    assert body["employee_seat"]["invite_url"].endswith("/signup?email=ann%40pilot.ie")


def test_invite_without_email_delivery_returns_the_link_and_a_clear_message(client, monkeypatch):
    monkeypatch.setattr(employee_seats_module, "send_employee_invite_email", lambda **kwargs: False)
    business = _create_business(client)
    _grant(client, business["id"])
    seat = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bob", "surname": "Staff", "email": "bob@pilot.ie", "role": "manager"},
        headers=_headers(),
    ).json()["employee_seat"]

    result = client.post(
        f"/businesses/{business['id']}/employee-seats/{seat['id']}/resend-invite", headers=_headers()
    )
    assert result.status_code == 200
    assert result.json()["email_sent"] is False
    assert result.json()["invite_url"].endswith("/signup?email=bob%40pilot.ie")
    assert "Copy the sign-up link" in result.json()["message"]

    listed = client.get(f"/businesses/{business['id']}/employee-seats", headers=_headers()).json()
    assert listed[0]["invite_url"].endswith("/signup?email=bob%40pilot.ie")


def test_removed_seat_has_no_invite_link(client, monkeypatch):
    monkeypatch.setattr(employee_seats_module, "send_employee_invite_email", lambda **kwargs: False)
    business = _create_business(client)
    _grant(client, business["id"])
    seat = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Cy", "surname": "Staff", "email": "cy@pilot.ie", "role": "staff"},
        headers=_headers(),
    ).json()["employee_seat"]
    assert client.delete(f"/businesses/{business['id']}/employee-seats/{seat['id']}", headers=_headers()).status_code in (200, 204)
    listed = client.get(f"/businesses/{business['id']}/employee-seats", headers=_headers()).json()
    assert listed[0]["invite_url"] is None
    with client._SessionLocal() as db:
        assert db.scalars(select(EmployeeSeat)).one().status == "canceled"


def test_grant_rejects_out_of_range_days_and_unknown_business(client):
    business = _create_business(client)
    with client._SessionLocal() as db:
        with pytest.raises(PilotAccessError):
            grant_pilot_access(db, business_id=uuid.UUID(business["id"]), days=0)
        with pytest.raises(PilotAccessError):
            grant_pilot_access(db, business_id=uuid.UUID(business["id"]), days=400)
        with pytest.raises(PilotAccessError):
            grant_pilot_access(db, business_id=uuid.uuid4(), days=30)


def test_owner_lookup_by_email_finds_only_their_standalone_business(client):
    business = _create_business(client)
    client.post("/businesses", json={"name": "Someone Else"}, headers=bearer_header("other", "other@x.ie"))
    with client._SessionLocal() as db:
        found = find_owned_businesses(db, owner_email="OWNER@pilot.ie")
    assert [str(b.id) for b in found] == [business["id"]]


def test_pilot_check_handles_naive_and_aware_datetimes():
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    assert pilot_access_active(Business(pilot_access_until=datetime(2026, 12, 1)), now) is True
    assert pilot_access_active(Business(pilot_access_until=datetime(2026, 11, 1, tzinfo=timezone.utc)), now) is False
    assert pilot_access_active(Business(pilot_access_until=None), now) is False
    assert pilot_access_active(None, now) is False
