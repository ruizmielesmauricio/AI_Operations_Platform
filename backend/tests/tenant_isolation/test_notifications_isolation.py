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


def test_staff_sees_every_operational_category(client):
    """stock / data_uploads / reports / orla_insights carry no
    visible_to_role — staff need these for daily operations (low stock,
    upload results, data freshness, reports, ORLA insights) per the
    Notification Centre permissions policy."""
    headers_owner = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers_owner, "Shop A")
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="staff-1", role="staff"))
    session.commit()
    session.close()

    for category in ("stock", "data_uploads", "reports", "orla_insights"):
        _seed_notification(client, business["id"], category=category, type_key=f"{category}_event")

    headers_staff = bearer_header("staff-1", "staff@example.com")
    staff_items = client.get(f"/businesses/{business['id']}/notifications", headers=headers_staff).json()["items"]
    assert {n["category"] for n in staff_items} == {"stock", "data_uploads", "reports", "orla_insights"}


def test_staff_cannot_see_any_owner_only_category(client):
    """team / billing / branches / security_account are the real
    notify_* functions' own visible_to_role="owner" — this seeds through
    those exact functions (not a raw notify() call) so the test exercises
    what's actually shipped, not just what the test claims."""
    from app.application.notifications import (
        notify_employee_activated,
        notify_employee_added,
        notify_employee_payment_failed,
        notify_employee_removed,
        notify_employee_role_changed,
        notify_subscription_status_change,
    )

    headers_owner = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers_owner, "Shop A")
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="staff-1", role="staff"))
    session.commit()

    db = client._SessionLocal()
    biz_id = uuid.UUID(business["id"])
    notify_employee_added(db, business_id=biz_id, seat_id=uuid.uuid4(), full_name="Aoife Byrne")
    notify_employee_activated(db, business_id=biz_id, seat_id=uuid.uuid4(), full_name="Aoife Byrne")
    notify_employee_payment_failed(db, business_id=biz_id, seat_id=uuid.uuid4(), full_name="Aoife Byrne")
    notify_employee_removed(db, business_id=biz_id, seat_id=uuid.uuid4(), full_name="Aoife Byrne")
    notify_employee_role_changed(db, business_id=biz_id, seat_id=uuid.uuid4(), full_name="Aoife Byrne", new_role="manager")
    notify_subscription_status_change(
        db, business_id=biz_id, business_name="Shop A", is_branch=False, new_status="past_due"
    )
    db.commit()
    db.close()

    headers_staff = bearer_header("staff-1", "staff@example.com")
    headers_owner_role = bearer_header("owner-1", "owner@example.com")
    staff_items = client.get(f"/businesses/{business['id']}/notifications", headers=headers_staff).json()["items"]
    owner_items = client.get(f"/businesses/{business['id']}/notifications", headers=headers_owner_role).json()["items"]

    assert staff_items == []
    assert {n["category"] for n in owner_items} == {"team", "security_account", "billing"}


def test_staff_cannot_see_branch_status_notifications(client):
    """Separate from the combined test above — notify_subscription_status_
    change's dedup_key is keyed by business_id alone, so exercising it
    with is_branch=True needs its own business/staff pairing rather than
    reusing one already given a non-branch call."""
    from app.application.notifications import notify_subscription_status_change

    headers_owner = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers_owner, "Galway")
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="staff-1", role="staff"))
    session.commit()

    db = client._SessionLocal()
    notify_subscription_status_change(
        db, business_id=uuid.UUID(business["id"]), business_name="Galway", is_branch=True, new_status="active"
    )
    db.commit()
    db.close()

    headers_staff = bearer_header("staff-1", "staff@example.com")
    headers_owner_role = bearer_header("owner-1", "owner@example.com")
    staff_items = client.get(f"/businesses/{business['id']}/notifications", headers=headers_staff).json()["items"]
    owner_items = client.get(f"/businesses/{business['id']}/notifications", headers=headers_owner_role).json()["items"]

    assert staff_items == []
    assert len(owner_items) == 1 and owner_items[0]["category"] == "branches"


def test_staff_unread_count_excludes_owner_only_rows(client):
    from app.application.notifications import notify_employee_added

    headers_owner = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers_owner, "Shop A")
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="staff-1", role="staff"))
    session.commit()

    db = client._SessionLocal()
    biz_id = uuid.UUID(business["id"])
    notify_employee_added(db, business_id=biz_id, seat_id=uuid.uuid4(), full_name="Aoife Byrne")  # owner-only
    db.commit()
    db.close()
    _seed_notification(client, business["id"], category="stock")  # operational, visible to all

    headers_staff = bearer_header("staff-1", "staff@example.com")
    headers_owner_role = bearer_header("owner-1", "owner@example.com")
    staff_unread = client.get(f"/businesses/{business['id']}/notifications/unread-count", headers=headers_staff).json()
    owner_unread = client.get(
        f"/businesses/{business['id']}/notifications/unread-count", headers=headers_owner_role
    ).json()

    assert staff_unread["unread_count"] == 1
    assert owner_unread["unread_count"] == 2


def test_staff_cannot_dismiss_an_owner_only_notification_by_guessed_id(client):
    headers_owner = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers_owner, "Shop A")
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="staff-1", role="staff"))
    session.commit()
    session.close()

    notification_id = _seed_notification(
        client, business["id"], category="billing", type_key="subscription_status_change",
        severity="warning", title="Payment issue", body="...", visible_to_role="owner",
    )
    headers_staff = bearer_header("staff-1", "staff@example.com")
    dismiss = client.post(f"/businesses/{business['id']}/notifications/{notification_id}/dismiss", headers=headers_staff)
    assert dismiss.status_code == 404

    # The row is untouched — owner can still see and dismiss it themselves.
    headers_owner_role = bearer_header("owner-1", "owner@example.com")
    owner_dismiss = client.post(
        f"/businesses/{business['id']}/notifications/{notification_id}/dismiss", headers=headers_owner_role
    )
    assert owner_dismiss.status_code == 200


def test_invalid_filter_values_return_422(client):
    headers = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers, "Shop A")

    bad_category = client.get(f"/businesses/{business['id']}/notifications?category=not_a_category", headers=headers)
    bad_status = client.get(f"/businesses/{business['id']}/notifications?status=archived", headers=headers)
    bad_severity = client.get(f"/businesses/{business['id']}/notifications?severity=urgent", headers=headers)

    assert bad_category.status_code == 422
    assert bad_status.status_code == 422
    assert bad_severity.status_code == 422

    # A valid value on the same route still works — the validation isn't
    # accidentally rejecting everything.
    ok = client.get(f"/businesses/{business['id']}/notifications?category=stock&status=unread", headers=headers)
    assert ok.status_code == 200


def test_pagination_metadata_and_limit_cap(client):
    headers = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers, "Shop A")
    for _ in range(3):
        _seed_notification(client, business["id"])

    page = client.get(f"/businesses/{business['id']}/notifications?limit=2&offset=0", headers=headers)
    assert page.status_code == 200
    body = page.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0

    # A caller asking for more than the cap never gets more than it —
    # FastAPI's Query(le=MAX_LIST_LIMIT) rejects it outright, same
    # enforcement point as the Transactions drill-down's own pagination cap.
    over_cap = client.get(f"/businesses/{business['id']}/notifications?limit=99999", headers=headers)
    assert over_cap.status_code == 422


def test_date_filter_query_params_validation(client):
    headers = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers, "Shop A")
    _seed_notification(client, business["id"])

    ok_today = client.get(f"/businesses/{business['id']}/notifications?date_filter=today", headers=headers)
    assert ok_today.status_code == 200
    assert len(ok_today.json()["items"]) == 1

    ok_custom = client.get(
        f"/businesses/{business['id']}/notifications?date_filter=custom&start_date=2026-01-01&end_date=2026-06-01",
        headers=headers,
    )
    assert ok_custom.status_code == 200

    reversed_range = client.get(
        f"/businesses/{business['id']}/notifications?date_filter=custom&start_date=2026-01-10&end_date=2026-01-01",
        headers=headers,
    )
    assert reversed_range.status_code == 422

    excessive_range = client.get(
        f"/businesses/{business['id']}/notifications?date_filter=custom&start_date=2000-01-01&end_date=2026-01-01",
        headers=headers,
    )
    assert excessive_range.status_code == 422

    missing_end_date = client.get(
        f"/businesses/{business['id']}/notifications?date_filter=custom&start_date=2026-01-01", headers=headers
    )
    assert missing_end_date.status_code == 422

    dates_without_custom = client.get(
        f"/businesses/{business['id']}/notifications?date_filter=today&start_date=2026-01-01", headers=headers
    )
    assert dates_without_custom.status_code == 422

    invalid_date_value = client.get(
        f"/businesses/{business['id']}/notifications?date_filter=custom&start_date=not-a-date&end_date=2026-01-01",
        headers=headers,
    )
    assert invalid_date_value.status_code == 422

    unsupported_filter = client.get(
        f"/businesses/{business['id']}/notifications?date_filter=last_year", headers=headers
    )
    assert unsupported_filter.status_code == 422


def test_date_filter_excludes_notifications_outside_the_range(client):
    headers = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers, "Shop A")
    old_id = _seed_notification(client, business["id"])

    # Backdate the seeded notification well outside "today".
    from datetime import datetime, timedelta, timezone

    db = client._SessionLocal()
    from app.models.notification import Notification

    row = db.get(Notification, uuid.UUID(old_id))
    row.created_at = datetime.now(timezone.utc) - timedelta(days=90)
    db.commit()
    db.close()

    today_view = client.get(f"/businesses/{business['id']}/notifications?date_filter=today", headers=headers)
    assert today_view.json()["items"] == []

    all_time_view = client.get(f"/businesses/{business['id']}/notifications", headers=headers)
    assert len(all_time_view.json()["items"]) == 1


def test_system_status_reports_an_active_incident_and_is_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")
    _seed_notification(
        client, business_a["id"], category="reports", type_key="report_delayed", severity="warning",
        title="delayed", body="...",
    )

    quiet = client.get(f"/businesses/{business_a['id']}/notifications/system-status", headers=headers_a)
    assert quiet.status_code == 200
    assert quiet.json()["has_active_incident"] is True
    assert len(quiet.json()["incidents"]) == 1

    other_business = client.get(f"/businesses/{business_b['id']}/notifications/system-status", headers=headers_b)
    assert other_business.json()["has_active_incident"] is False


def test_system_status_ignores_non_incident_notification_types(client):
    headers = bearer_header("owner-1", "owner@example.com")
    business = _create_business(client, headers, "Shop A")
    _seed_notification(client, business["id"])  # default low_stock_summary — not an incident type_key

    response = client.get(f"/businesses/{business['id']}/notifications/system-status", headers=headers)
    assert response.json() == {"has_active_incident": False, "incidents": []}
