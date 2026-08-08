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
    yield TestClient(app)
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
            "manager_name": "Aoife Byrne",
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
    assert body["manager_name"] == "Aoife Byrne"
    assert body["contact_email"] == "aoife@shopa.example"
    assert body["location_label"] == "Dublin - Rathmines"
    assert body["country"] == "Ireland"

    # Persisted, not just echoed back.
    refetched = client.get(f"/businesses/{business['id']}", headers=headers).json()
    assert refetched["manager_name"] == "Aoife Byrne"


def test_patch_only_touches_fields_actually_sent(client):
    # exclude_unset semantics: a field left out of the request body is
    # left untouched, not silently cleared.
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.patch(f"/businesses/{business['id']}", json={"manager_name": "Aoife Byrne"}, headers=headers)

    response = client.patch(
        f"/businesses/{business['id']}", json={"contact_email": "aoife@shopa.example"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    # manager_name survives the second PATCH, which never mentioned it.
    assert body["manager_name"] == "Aoife Byrne"
    assert body["contact_email"] == "aoife@shopa.example"


def test_a_non_member_cannot_update_another_business_s_profile(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()

    response = client.patch(
        f"/businesses/{business_a['id']}", json={"manager_name": "Not Owner"}, headers=headers_b
    )
    assert response.status_code == 403

    # Confirmed untouched.
    refetched = client.get(f"/businesses/{business_a['id']}", headers=headers_a).json()
    assert refetched["manager_name"] is None


# --- POST /businesses/{id}/validate-address ---------------------------------


def test_validate_address_requires_membership(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()

    response = client.post(
        f"/businesses/{business['id']}/validate-address", json={"address_line1": "1 Main St"}, headers=headers_b
    )
    assert response.status_code == 403


def test_validate_address_degrades_gracefully_when_not_configured(client):
    # No GEOAPIFY_API_KEY in the test environment — proves the route
    # never 500s just because address validation isn't set up, it
    # returns a normal, honest "not matched" response.
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.post(
        f"/businesses/{business['id']}/validate-address",
        json={"address_line1": "1 Main St", "city": "Dublin"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["reason"]


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
