"""Covers the company-logo upload feature end to end through the real API
routes (app/api/businesses.py::upload_logo/get_logo/delete_logo) — owner-
only enforcement on POST/DELETE, content-type/size validation, the
deliberately-public GET, and that a delete actually clears both R2 and the
has_logo flag. R2 itself is monkeypatched to an in-memory dict (same style
already used for r2_client in tests/integration/test_importer_service.py),
never a real network call.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "business_logo_api_test.db"
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

    # In-memory stand-in for R2 — keyed exactly like the real bucket
    # would be, so a wrong storage_key (e.g. cross-business collision)
    # would show up as a test failure, not silently pass.
    store: dict[str, tuple[bytes, str]] = {}

    def _put(*, storage_key, data, content_type):
        store[storage_key] = (data, content_type)

    def _download(*, storage_key):
        return store[storage_key][0]

    def _delete(*, storage_key):
        store.pop(storage_key, None)

    monkeypatch.setattr(r2_client, "put_object_bytes", _put)
    monkeypatch.setattr(r2_client, "download_object", _download)
    monkeypatch.setattr(r2_client, "delete_object", _delete)

    test_client = TestClient(app)
    test_client._SessionLocal = TestSessionLocal
    yield test_client
    app.dependency_overrides.clear()


def _png_bytes() -> bytes:
    # A minimal valid PNG header is not required — the route only checks
    # the declared Content-Type and byte length, never sniffs content
    # (same posture as the rest of this app's upload validation).
    return b"\x89PNG\r\n\x1a\n" + b"0" * 100


def test_owner_can_upload_a_logo_and_has_logo_flips_true(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    assert business["has_logo"] is False

    response = client.post(
        f"/businesses/{business['id']}/logo",
        headers=headers,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["has_logo"] is True


def test_uploaded_logo_is_served_publicly_with_the_right_bytes_and_content_type(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    payload = _png_bytes()
    client.post(
        f"/businesses/{business['id']}/logo",
        headers=headers,
        files={"file": ("logo.png", payload, "image/png")},
    )

    # Deliberately no Authorization header — this route is public.
    response = client.get(f"/businesses/{business['id']}/logo")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "image/png"


def test_a_business_with_no_logo_404s_on_get(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.get(f"/businesses/{business['id']}/logo")

    assert response.status_code == 404


def test_get_logo_404s_for_a_nonexistent_business(client):
    response = client.get(f"/businesses/{uuid.uuid4()}/logo")

    assert response.status_code == 404


def test_a_non_owner_member_cannot_upload_a_logo(client):
    from app.models.membership import Membership

    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="staff"))
    session.commit()
    session.close()

    response = client.post(
        f"/businesses/{business['id']}/logo",
        headers=headers_staff,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 403


def test_wrong_content_type_is_rejected_with_400(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.post(
        f"/businesses/{business['id']}/logo",
        headers=headers,
        files={"file": ("logo.pdf", b"%PDF-1.4 not an image", "application/pdf")},
    )

    assert response.status_code == 400


def test_oversized_logo_is_rejected_with_413(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    oversized = b"0" * (5 * 1024 * 1024 + 1)

    response = client.post(
        f"/businesses/{business['id']}/logo",
        headers=headers,
        files={"file": ("logo.png", oversized, "image/png")},
    )

    assert response.status_code == 413


def test_owner_can_delete_the_logo_and_get_404s_afterward(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.post(
        f"/businesses/{business['id']}/logo",
        headers=headers,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )

    response = client.delete(f"/businesses/{business['id']}/logo", headers=headers)

    assert response.status_code == 200
    assert response.json()["has_logo"] is False
    assert client.get(f"/businesses/{business['id']}/logo").status_code == 404


def test_a_non_owner_member_cannot_delete_the_logo(client):
    from app.models.membership import Membership

    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    client.post(
        f"/businesses/{business['id']}/logo",
        headers=headers_owner,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="staff"))
    session.commit()
    session.close()

    response = client.delete(f"/businesses/{business['id']}/logo", headers=headers_staff)

    assert response.status_code == 403
    assert client.get(f"/businesses/{business['id']}/logo").status_code == 200


def test_deleting_when_no_logo_exists_is_a_no_op_204_shaped_success(client):
    # Idempotent: calling delete on a business that never had a logo
    # should not 404 or 500 — there's simply nothing to clear.
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.delete(f"/businesses/{business['id']}/logo", headers=headers)

    assert response.status_code == 200
    assert response.json()["has_logo"] is False


def test_cross_tenant_user_cannot_upload_or_delete_another_business_s_logo(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()

    upload_response = client.post(
        f"/businesses/{business_b['id']}/logo",
        headers=headers_a,
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )
    assert upload_response.status_code == 403

    delete_response = client.delete(f"/businesses/{business_b['id']}/logo", headers=headers_a)
    assert delete_response.status_code == 403
