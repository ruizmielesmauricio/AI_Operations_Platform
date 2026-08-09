import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from app.models.audit_log import AuditLog
from app.models.membership import Membership
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "audit_log_isolation_test.db"
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
    test_client = TestClient(app)
    test_client._SessionLocal = TestSessionLocal
    yield test_client
    app.dependency_overrides.clear()


def test_missing_token_is_rejected(client):
    business = client.post(
        "/businesses", json={"name": "Shop A"}, headers=bearer_header("user-a", "a@example.com")
    ).json()
    response = client.get(f"/businesses/{business['id']}/audit-logs")
    assert response.status_code == 401


def test_owner_can_list_audit_events_for_their_business(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.patch(f"/businesses/{business['id']}", json={"manager_name": "Aoife Byrne"}, headers=headers)

    response = client.get(f"/businesses/{business['id']}/audit-logs", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["action"] == "business_profile_updated"
    assert body[0]["user_id"] == "user-a"


def test_events_are_ordered_newest_first(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.patch(f"/businesses/{business['id']}", json={"manager_name": "First"}, headers=headers)
    client.patch(f"/businesses/{business['id']}", json={"manager_name": "Second"}, headers=headers)
    client.patch(f"/businesses/{business['id']}", json={"manager_name": "Third"}, headers=headers)

    body = client.get(f"/businesses/{business['id']}/audit-logs", headers=headers).json()
    assert len(body) == 3
    assert [row["event_metadata"]["fields_changed"] for row in body] == [
        ["manager_name"],
        ["manager_name"],
        ["manager_name"],
    ]
    timestamps = [row["created_at"] for row in body]
    assert timestamps == sorted(timestamps, reverse=True)


def test_metadata_never_carries_the_actual_profile_values(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.patch(
        f"/businesses/{business['id']}",
        json={"manager_name": "Aoife Byrne", "contact_email": "aoife@shopa.example"},
        headers=headers,
    )

    body = client.get(f"/businesses/{business['id']}/audit-logs", headers=headers).json()
    serialized = str(body)
    assert "Aoife Byrne" not in serialized
    assert "aoife@shopa.example" not in serialized
    assert set(body[0]["event_metadata"]["fields_changed"]) == {"manager_name", "contact_email"}


def test_events_are_tenant_scoped_and_cross_tenant_access_is_forbidden(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()
    client.patch(f"/businesses/{business_a['id']}", json={"manager_name": "A"}, headers=headers_a)
    client.patch(f"/businesses/{business_b['id']}", json={"manager_name": "B"}, headers=headers_b)

    # Never trusts business_id from the URL alone — B has no membership on A.
    response = client.get(f"/businesses/{business_a['id']}/audit-logs", headers=headers_b)
    assert response.status_code == 403

    # A's own listing never contains B's events.
    own = client.get(f"/businesses/{business_a['id']}/audit-logs", headers=headers_a).json()
    assert len(own) == 1
    assert own[0]["target_id"] == business_a["id"]


def test_a_staff_member_is_denied(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="staff"))
    session.commit()
    session.close()

    response = client.get(f"/businesses/{business['id']}/audit-logs", headers=headers_staff)
    assert response.status_code == 403


def test_listing_audit_logs_does_not_itself_create_an_audit_event(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.patch(f"/businesses/{business['id']}", json={"manager_name": "Aoife"}, headers=headers)

    client.get(f"/businesses/{business['id']}/audit-logs", headers=headers)
    client.get(f"/businesses/{business['id']}/audit-logs", headers=headers)

    session = client._SessionLocal()
    rows = session.query(AuditLog).filter(AuditLog.business_id == uuid.UUID(business["id"])).all()
    session.close()
    assert len(rows) == 1  # only the original profile-update write, reads left no trace
