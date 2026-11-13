"""Tenant isolation for the support handoff (PR-5.7, PR-6.1): a business's
support requests and support notifications are never readable or
writable from another business, and staff see only their own requests.
The help articles themselves are public product documentation."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from app.models.membership import Membership
from app.models.support_request import SupportRequest
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'support_isolation_test.db'}")
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


def _create_business(client, headers, name):
    return client.post("/businesses", json={"name": name}, headers=headers).json()


def _ask_support(client, business_id, headers, question="How do I connect ORLA to Shopify?"):
    return client.post(
        f"/businesses/{business_id}/support/requests", json={"question": question, "source": "help_page"},
        headers=headers,
    )


def test_create_and_list_are_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    created = _ask_support(client, business_a["id"], headers_a)
    assert created.status_code == 201
    assert created.json()["requester_email"] == "a@example.com"

    assert client.get(f"/businesses/{business_a['id']}/support/requests", headers=headers_a).json()[0]["id"] == created.json()["id"]
    assert client.get(f"/businesses/{business_b['id']}/support/requests", headers=headers_b).json() == []


def test_cannot_create_or_list_support_requests_for_another_business(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    _create_business(client, headers_b, "Shop B")
    _ask_support(client, business_a["id"], headers_a)

    assert _ask_support(client, business_a["id"], headers_b).status_code == 403
    assert client.get(f"/businesses/{business_a['id']}/support/requests", headers=headers_b).status_code == 403

    session = client._SessionLocal()
    rows = session.query(SupportRequest).all()
    session.close()
    assert len(rows) == 1 and str(rows[0].business_id) == business_a["id"]


def test_support_notification_is_owner_only_and_never_crosses_tenants(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-s", "s@example.com")
    headers_other = bearer_header("user-b", "b@example.com")
    business = _create_business(client, headers_owner, "Shop A")
    other = _create_business(client, headers_other, "Shop B")
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-s", role="staff"))
    session.commit()
    session.close()

    assert _ask_support(client, business["id"], headers_staff).status_code == 201

    owner_items = client.get(f"/businesses/{business['id']}/notifications?category=support", headers=headers_owner).json()["items"]
    staff_items = client.get(f"/businesses/{business['id']}/notifications?category=support", headers=headers_staff).json()["items"]
    other_items = client.get(f"/businesses/{other['id']}/notifications?category=support", headers=headers_other).json()["items"]
    assert len(owner_items) == 1 and "s@example.com" in owner_items[0]["body"]
    assert staff_items == []
    assert other_items == []


def test_staff_see_only_their_own_requests_owner_sees_all(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-s", "s@example.com")
    business = _create_business(client, headers_owner, "Shop A")
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-s", role="staff"))
    session.commit()
    session.close()

    _ask_support(client, business["id"], headers_owner, question="Owner question")
    _ask_support(client, business["id"], headers_staff, question="Staff question")

    owner_list = client.get(f"/businesses/{business['id']}/support/requests", headers=headers_owner).json()
    staff_list = client.get(f"/businesses/{business['id']}/support/requests", headers=headers_staff).json()
    assert {r["question"] for r in owner_list} == {"Owner question", "Staff question"}
    assert [r["question"] for r in staff_list] == ["Staff question"]


def test_duplicate_submit_returns_the_existing_request(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")

    first = _ask_support(client, business["id"], headers)
    second = _ask_support(client, business["id"], headers)

    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_support_requests_require_authentication(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")
    response = client.post(f"/businesses/{business['id']}/support/requests", json={"question": "Hi"})
    assert response.status_code == 401


def test_help_articles_are_public_and_read_only(client):
    listing = client.get("/help/articles")
    assert listing.status_code == 200
    assert any(a["slug"] == "upload-stock-count" for a in listing.json())

    search = client.get("/help/articles", params={"q": "how do I upload my stock count"}).json()
    assert search[0]["slug"] == "upload-stock-count" and search[0]["score"] > 0

    article = client.get("/help/articles/contact-support").json()
    assert article["title"] == "Contact ORLA support" and article["sections"]
    assert client.get("/help/articles/../../etc/passwd").status_code == 404
    assert client.get("/help/articles/not-an-article").status_code == 404
    assert client.post("/help/articles", json={}).status_code == 405
