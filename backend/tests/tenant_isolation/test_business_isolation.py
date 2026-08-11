import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh, isolated database per test, wired into the FastAPI app via
    dependency override — proves the real route/dependency wiring, not a
    reimplementation of it.
    """
    patch_jwks(monkeypatch)
    db_path = tmp_path / "tenant_isolation_test.db"
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
    test_client._SessionLocal = TestSessionLocal  # stashed for direct audit-log assertions
    yield test_client
    app.dependency_overrides.clear()


def test_missing_token_is_rejected(client):
    response = client.post("/businesses", json={"name": "No Auth Shop"})
    assert response.status_code == 401


def test_owner_can_create_and_read_their_own_business(client):
    headers = bearer_header("user-a", "a@example.com")
    create_response = client.post("/businesses", json={"name": "Shop A"}, headers=headers)
    assert create_response.status_code == 201
    business_id = create_response.json()["id"]

    get_response = client.get(f"/businesses/{business_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["role"] == "owner"


def test_cross_tenant_access_is_forbidden(client):
    """The core tenant-isolation guarantee (PR-6.1/6.2, ED-008): business A
    can never read business B's data, even though the browser can put
    business B's real id in the URL.
    """
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")

    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    client.post("/businesses", json={"name": "Shop B"}, headers=headers_b)

    # User B tries to read business A's data using A's real id.
    response = client.get(f"/businesses/{business_a['id']}", headers=headers_b)
    assert response.status_code == 403


def test_listing_businesses_only_returns_the_caller_s_own(client):
    # One business per account (see test_business_limit below) means this
    # can no longer prove isolation via two businesses under the same
    # owner — three distinct users each owning exactly one is the closest
    # equivalent scope: user A's list must show only their own, never B's
    # or C's.
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    headers_c = bearer_header("user-c", "c@example.com")

    client.post("/businesses", json={"name": "Shop A"}, headers=headers_a)
    client.post("/businesses", json={"name": "Shop B"}, headers=headers_b)
    client.post("/businesses", json={"name": "Shop C"}, headers=headers_c)

    response = client.get("/businesses", headers=headers_a)
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert names == {"Shop A"}


def test_business_limit_rejects_a_second_standalone_business_for_the_same_owner(client):
    # Real regression risk this whole feature exists to prevent: a second
    # POST /businesses for the same owner must be rejected, not silently
    # create a second shop.
    headers = bearer_header("user-a", "a@example.com")
    first = client.post("/businesses", json={"name": "Shop A"}, headers=headers)
    assert first.status_code == 201

    second = client.post("/businesses", json={"name": "Shop A2"}, headers=headers)
    assert second.status_code == 409

    # And the rejected attempt must not have partially created anything —
    # the account still shows exactly the one business.
    response = client.get("/businesses", headers=headers)
    names = {row["name"] for row in response.json()}
    assert names == {"Shop A"}


# --- PATCH /businesses/{id} (profile fields) --------------------------------


def test_owner_can_update_their_business_profile(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.patch(
        f"/businesses/{business['id']}",
        json={
            "manager_first_name": "Aoife",
            "manager_surname": "Byrne",
            "contact_email": "aoife@shopa.example",
            "contact_phone": "+353 1 234 5678",
            "location_label": "Dublin - Rathmines",
            "address_line1": "12 Main Street",
            "city": "Dublin",
            "postal_code": "D06",
            "country": "Ireland",
            "timezone": "Europe/Dublin",
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manager_first_name"] == "Aoife"
    assert body["manager_surname"] == "Byrne"
    assert body["contact_email"] == "aoife@shopa.example"
    assert body["location_label"] == "Dublin - Rathmines"
    assert body["country"] == "Ireland"

    # Persisted, not just echoed back.
    refetched = client.get(f"/businesses/{business['id']}", headers=headers).json()
    assert refetched["manager_first_name"] == "Aoife"
    assert refetched["manager_surname"] == "Byrne"


def test_patch_only_touches_fields_actually_sent(client):
    # exclude_unset semantics: a field left out of the request body is
    # left untouched, not silently cleared.
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.patch(f"/businesses/{business['id']}", json={"manager_first_name": "Aoife"}, headers=headers)

    response = client.patch(
        f"/businesses/{business['id']}", json={"contact_email": "aoife@shopa.example"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    # manager_first_name survives the second PATCH, which never mentioned it.
    assert body["manager_first_name"] == "Aoife"
    assert body["contact_email"] == "aoife@shopa.example"


def test_a_non_member_cannot_update_another_business_s_profile(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()

    response = client.patch(
        f"/businesses/{business_a['id']}", json={"manager_first_name": "Not Owner"}, headers=headers_b
    )
    assert response.status_code == 403

    # Confirmed untouched.
    refetched = client.get(f"/businesses/{business_a['id']}", headers=headers_a).json()
    assert refetched["manager_first_name"] is None


def test_a_genuine_staff_member_cannot_update_the_business_profile(client):
    """Distinct from test_a_non_member_cannot_update_another_business_s_profile
    above: user-b here IS a real member of this same business (staff),
    not a stranger — exercises the owner-only role check itself
    (Company Profile permissions batch), not get_current_membership's
    separate "not a member at all" rejection."""
    import uuid

    from app.models.membership import Membership

    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="staff"))
    session.commit()
    session.close()

    response = client.patch(
        f"/businesses/{business['id']}", json={"manager_first_name": "Not Owner"}, headers=headers_staff
    )
    assert response.status_code == 403

    refetched = client.get(f"/businesses/{business['id']}", headers=headers_owner).json()
    assert refetched["manager_first_name"] is None


# --- PR-6.5: audit logging for profile changes -------------------------------


def test_updating_a_profile_creates_an_audit_entry_with_field_names_not_values(client):
    import uuid

    from app.models.audit_log import AuditLog

    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.patch(
        f"/businesses/{business['id']}",
        json={"manager_first_name": "Aoife", "manager_surname": "Byrne", "contact_email": "aoife@shopa.example"},
        headers=headers,
    )
    assert response.status_code == 200

    session = client._SessionLocal()
    rows = session.query(AuditLog).filter(AuditLog.business_id == uuid.UUID(business["id"])).all()
    session.close()

    assert len(rows) == 1
    entry = rows[0]
    assert entry.action == "business_profile_updated"
    assert entry.user_id == "user-a"
    assert entry.target_type == "business"
    assert entry.target_id == business["id"]
    # Field names, not the actual values — "Aoife"/"Byrne"/the email
    # address must never appear in the log itself.
    assert set(entry.event_metadata["fields_changed"]) == {"manager_first_name", "manager_surname", "contact_email"}
    serialized = str(entry.event_metadata)
    assert "Aoife" not in serialized
    assert "Byrne" not in serialized
    assert "aoife@shopa.example" not in serialized


def test_a_rejected_profile_update_creates_no_audit_entry(client):
    import uuid

    from app.models.audit_log import AuditLog

    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()

    response = client.patch(
        f"/businesses/{business_a['id']}", json={"manager_first_name": "Not Owner"}, headers=headers_b
    )
    assert response.status_code == 403

    session = client._SessionLocal()
    rows = session.query(AuditLog).filter(AuditLog.business_id == uuid.UUID(business_a["id"])).all()
    session.close()
    assert rows == []


def test_a_genuine_staff_member_s_rejected_profile_update_creates_no_audit_entry(client):
    import uuid

    from app.models.audit_log import AuditLog
    from app.models.membership import Membership

    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="staff"))
    session.commit()

    response = client.patch(
        f"/businesses/{business['id']}", json={"manager_first_name": "Not Owner"}, headers=headers_staff
    )
    assert response.status_code == 403

    rows = session.query(AuditLog).filter(AuditLog.business_id == uuid.UUID(business["id"])).all()
    session.close()
    assert rows == []


# --- GET /businesses/{id}/address-suggestions -------------------------------


def test_address_suggestions_requires_membership(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()

    response = client.get(
        f"/businesses/{business['id']}/address-suggestions", params={"text": "1 Main St"}, headers=headers_b
    )
    assert response.status_code == 403


def test_address_suggestions_returns_an_empty_list_when_geocoding_is_unavailable(client, monkeypatch):
    # Explicitly mocked at the service boundary, not relying on
    # GEOAPIFY_API_KEY being absent from the real .env — a real key now
    # exists there (this app's own dev setup), so relying on absence
    # would silently start making a real live Geoapify network call from
    # every test run instead of actually testing this path, a real gap
    # caught live once a key was actually added. app/geocoding/service.py
    # itself already catches GeocodingNotConfigured/GeocodingProviderError
    # internally and returns an empty list rather than raising — this
    # proves the route surfaces that contract correctly, without
    # depending on what's really configured or ever calling out over the
    # network.
    from app.api import businesses as businesses_api

    monkeypatch.setattr(businesses_api, "suggest_addresses", lambda text: [])

    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.get(
        f"/businesses/{business['id']}/address-suggestions", params={"text": "1 Main St"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json() == []


def test_address_suggestions_returns_real_suggestions(client, monkeypatch):
    from app.api import businesses as businesses_api
    from app.geocoding.service import AddressSuggestion

    monkeypatch.setattr(
        businesses_api,
        "suggest_addresses",
        lambda text: [
            AddressSuggestion(
                formatted_address="12 Main Street, Dublin, Ireland", city="Dublin", timezone="Europe/Dublin"
            )
        ],
    )

    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.get(
        f"/businesses/{business['id']}/address-suggestions", params={"text": "12 Main"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["formatted_address"] == "12 Main Street, Dublin, Ireland"
    assert body[0]["timezone"] == "Europe/Dublin"


def test_include_deleted_only_ever_shows_the_caller_s_own_archived_businesses(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    client.delete(f"/businesses/{business_a['id']}", headers=headers_a)

    # Default: archived business stays hidden even for its own owner.
    assert client.get("/businesses", headers=headers_a).json() == []

    # Opt-in shows it back to its own owner...
    own_list = client.get("/businesses?include_deleted=true", headers=headers_a).json()
    assert {row["name"] for row in own_list} == {"Shop A"}

    # ...but never to a different user, opted in or not.
    other_list = client.get("/businesses?include_deleted=true", headers=headers_b).json()
    assert other_list == []
