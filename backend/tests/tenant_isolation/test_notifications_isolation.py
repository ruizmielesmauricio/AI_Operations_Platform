import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.application.notifications import notify
from app.main import app
from app.models import Base
from app.models.membership import Membership
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "notifications_isolation_test.db"
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


def _create_business(client, headers, name):
    return client.post("/businesses", json={"name": name}, headers=headers).json()


def _seed_notification(client, business_id, **kwargs):
    db = client._SessionLocal()
    defaults = dict(
        business_id=uuid.UUID(business_id), category="stock", type_key="low_stock_summary",
        severity="warning", title="3 products below reorder point", body="...",
    )
    defaults.update(kwargs)
    n = notify(db, **defaults)
    db.commit()
    n_id = str(n.id)
    db.close()
    return n_id


def test_notifications_list_is_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")
    _seed_notification(client, business_a["id"])

    response_a = client.get(f"/businesses/{business_a['id']}/notifications", headers=headers_a)
    response_b = client.get(f"/businesses/{business_b['id']}/notifications", headers=headers_b)

    assert response_a.status_code == 200
    assert len(response_a.json()["items"]) == 1
    assert response_b.status_code == 200
    assert response_b.json()["items"] == []


def test_cannot_read_or_dismiss_another_businesss_notification(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    _create_business(client, headers_b, "Shop B")
    notification_id = _seed_notification(client, business_a["id"])

    # Business B can't mark/dismiss business A's notification by guessing
    # the id, even scoped under its own business_id in the URL — the
    # lookup itself is tenant-scoped, not just the list.
    headers_c = bearer_header("user-c", "c@example.com")
    cross_business = _create_business(client, headers_c, "Shop C")
    cross_read = client.post(
        f"/businesses/{cross_business['id']}/notifications/{notification_id}/read", headers=headers_c
    )
    assert cross_read.status_code == 404

    own_read = client.post(f"/businesses/{business_a['id']}/notifications/{notification_id}/read", headers=headers_a)
    assert own_read.status_code == 200
    assert own_read.json()["status"] == "read"


def test_billing_category_is_owner_only(client):
    headers_owner = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers_owner, "Shop A")
    _seed_notification(
        client, business["id"], category="billing", type_key="subscription_status_change",
        severity="warning", title="Payment issue", body="...", visible_to_role="owner",
    )

    db = client._SessionLocal()
    db.add(Membership(business_id=uuid.UUID(business["id"]), user_id="staff-1", role="staff"))
    db.commit()
    db.close()
    headers_staff = bearer_header("staff-1", "staff@example.com")

    owner_view = client.get(f"/businesses/{business['id']}/notifications", headers=headers_owner)
    staff_view = client.get(f"/businesses/{business['id']}/notifications", headers=headers_staff)

    assert len(owner_view.json()["items"]) == 1
    assert staff_view.json()["items"] == []
    assert staff_view.json()["unread_count"] == 0
    assert owner_view.json()["unread_count"] == 1

    # Staff can't reach the owner-only row even by id.
    notification_id = owner_view.json()["items"][0]["id"]
    staff_read = client.post(
        f"/businesses/{business['id']}/notifications/{notification_id}/read", headers=headers_staff
    )
    assert staff_read.status_code == 404


def test_mark_all_read_and_dismiss_and_filters(client):
    headers = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers, "Shop A")
    _seed_notification(client, business["id"], category="stock", type_key="a", title="A")
    _seed_notification(client, business["id"], category="reports", type_key="b", title="B")

    filtered = client.get(f"/businesses/{business['id']}/notifications?category=reports", headers=headers)
    assert len(filtered.json()["items"]) == 1
    assert filtered.json()["items"][0]["title"] == "B"

    mark_all = client.post(f"/businesses/{business['id']}/notifications/mark-all-read", headers=headers)
    assert mark_all.json()["updated"] == 2
    unread = client.get(f"/businesses/{business['id']}/notifications/unread-count", headers=headers)
    assert unread.json()["unread_count"] == 0

    notification_id = filtered.json()["items"][0]["id"]
    dismissed = client.post(f"/businesses/{business['id']}/notifications/{notification_id}/dismiss", headers=headers)
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"

    default_view = client.get(f"/businesses/{business['id']}/notifications", headers=headers)
    assert notification_id not in [n["id"] for n in default_view.json()["items"]]
