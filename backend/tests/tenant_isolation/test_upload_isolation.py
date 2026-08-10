import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks, seed_active_subscription


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    monkeypatch.setattr(
        r2_client, "generate_upload_url", lambda *, storage_key: f"https://r2.test/{storage_key}"
    )
    db_path = tmp_path / "upload_isolation_test.db"
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
    test_client._engine = engine  # stashed so _create_business can seed an active subscription
    yield test_client
    app.dependency_overrides.clear()


def _create_business(client, headers, name):
    # Uploads/imports now require an active subscription
    # (app/billing/access.py::require_active_subscription) — seeded here,
    # bypassing Stripe entirely, since every test in this file is about
    # upload/tenant-isolation behavior, not billing state.
    business = client.post("/businesses", json={"name": name}, headers=headers).json()
    seed_active_subscription(client._engine, business["id"])
    return business


def test_uploading_without_an_active_subscription_is_blocked(client):
    # Direct API call, not _create_business (which always seeds an active
    # subscription for every other test in this file) — proves the real
    # revenue-protection gate this feature exists for.
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.post(
        f"/businesses/{business['id']}/uploads",
        json={"filename": "sales.csv", "entity_type": "sales"},
        headers=headers,
    )
    assert response.status_code == 402

    seed_active_subscription(client._engine, business["id"])
    response = client.post(
        f"/businesses/{business['id']}/uploads",
        json={"filename": "sales.csv", "entity_type": "sales"},
        headers=headers,
    )
    assert response.status_code == 201


def test_uploading_requires_membership_of_the_business(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")

    response = client.post(
        f"/businesses/{business_a['id']}/uploads",
        json={"filename": "sales.csv", "entity_type": "sales"},
        headers=headers_b,
    )

    assert response.status_code == 403


def test_owner_can_request_an_upload_url_and_complete_it(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")

    create_response = client.post(
        f"/businesses/{business['id']}/uploads",
        json={"filename": "sales.csv", "entity_type": "sales"},
        headers=headers,
    )
    assert create_response.status_code == 201
    upload_id = create_response.json()["id"]
    assert create_response.json()["upload_url"].startswith("https://r2.test/")

    complete_response = client.post(
        f"/businesses/{business['id']}/uploads/{upload_id}/complete", headers=headers
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "uploaded"


def test_unsupported_file_type_is_rejected(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")

    response = client.post(
        f"/businesses/{business['id']}/uploads",
        json={"filename": "sales.pdf", "entity_type": "sales"},
        headers=headers,
    )

    assert response.status_code == 400


def test_cross_tenant_cannot_list_or_complete_another_business_s_upload(client):
    """The core tenant-isolation guarantee (PR-6.1/6.2, ED-008) extended to
    uploads: business A's upload id must be unusable by business B, even
    when B knows the real id.
    """
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    create_response = client.post(
        f"/businesses/{business_a['id']}/uploads",
        json={"filename": "sales.csv", "entity_type": "sales"},
        headers=headers_a,
    )
    upload_id = create_response.json()["id"]

    # B tries to complete A's upload via B's own (legitimate) business id.
    complete_response = client.post(
        f"/businesses/{business_b['id']}/uploads/{upload_id}/complete", headers=headers_b
    )
    assert complete_response.status_code == 404

    list_response = client.get(f"/businesses/{business_b['id']}/uploads", headers=headers_b)
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_listing_uploads_only_returns_the_business_s_own(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")

    client.post(
        f"/businesses/{business['id']}/uploads",
        json={"filename": "a.csv", "entity_type": "sales"},
        headers=headers,
    )
    client.post(
        f"/businesses/{business['id']}/uploads",
        json={"filename": "b.xlsx", "entity_type": "sales"},
        headers=headers,
    )

    response = client.get(f"/businesses/{business['id']}/uploads", headers=headers)
    assert response.status_code == 200
    filenames = {row["original_filename"] for row in response.json()}
    assert filenames == {"a.csv", "b.xlsx"}
