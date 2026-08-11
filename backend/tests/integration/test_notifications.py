"""ORLA Notification Centre — app/application/notifications.py's notify()
dedup/reopen semantics, and each concrete trigger's content, against a
real (SQLite) database. API-level tenant isolation and role visibility
live in tests/tenant_isolation/test_notifications_isolation.py instead,
matching this codebase's own split (see tests/tenant_isolation/README.md).
"""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from datetime import datetime, timedelta, timezone

from app.application.alerts import refresh_low_stock_alerts
from app.application.employee_seats import add_employee, delete_employee, try_activate_employee_seat, update_employee_profile
from app.application.notifications import (
    check_data_freshness,
    notify,
    notify_employee_activated,
    notify_import_completed,
    notify_low_stock_summary,
    notify_orla_insights,
    notify_report_failed,
    notify_report_ready,
    notify_subscription_status_change,
    resolve_data_freshness,
)
from app.billing import client as billing_client
from app.models.business import Business
from app.models.import_record import ImportRecord
from app.models.membership import Membership
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.models.upload import Upload
from app.models.user import User
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.notification import NotificationRepository
from app.scheduler.tick import run_tick
from app.settings.config import get_settings


@pytest.fixture(autouse=True)
def _seat_price(monkeypatch):
    monkeypatch.setenv("STRIPE_EMPLOYEE_SEAT_PRICE_ID", "price_employee_seat")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fake_checkout(monkeypatch):
    def fake_create_checkout_session(**kwargs):
        return SimpleNamespace(url="https://checkout.stripe.com/fake")

    monkeypatch.setattr(billing_client, "create_checkout_session", fake_create_checkout_session)
    monkeypatch.setattr(billing_client, "cancel_subscription", lambda *a, **k: None)


def _seed_user(db_session, user_id, email):
    db_session.add(User(id=user_id, email=email))
    db_session.commit()


# --- notify() dedup/reopen -------------------------------------------------


def test_notify_without_dedup_key_always_creates_a_new_row(db_session, business_id):
    notify(db_session, business_id=business_id, category="team", type_key="employee_added",
           severity="info", title="A", body="a")
    notify(db_session, business_id=business_id, category="team", type_key="employee_added",
           severity="info", title="B", body="b")
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    assert len(rows) == 2


def test_notify_with_dedup_key_updates_the_existing_open_row(db_session, business_id):
    dedup_key = f"low_stock_summary:{business_id}"
    notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
           severity="warning", title="3 products below reorder point", body="...", dedup_key=dedup_key)
    db_session.commit()

    notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
           severity="warning", title="5 products below reorder point", body="updated", dedup_key=dedup_key)
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    assert len(rows) == 1
    assert rows[0].title == "5 products below reorder point"


def test_reopening_a_read_notification_flips_it_back_to_unread(db_session, business_id):
    dedup_key = f"low_stock_summary:{business_id}"
    n = notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
               severity="warning", title="t", body="b", dedup_key=dedup_key)
    db_session.commit()
    NotificationRepository(db_session).mark_read(n)
    db_session.commit()
    assert n.status == "read"

    notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
           severity="warning", title="t2", body="b2", dedup_key=dedup_key)
    db_session.commit()
    db_session.refresh(n)
    assert n.status == "unread"
    assert n.read_at is None


def test_dismissed_notification_is_never_reopened_a_new_row_is_created_instead(db_session, business_id):
    dedup_key = f"low_stock_summary:{business_id}"
    n = notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
               severity="warning", title="t", body="b", dedup_key=dedup_key)
    db_session.commit()
    NotificationRepository(db_session).dismiss(n)
    db_session.commit()

    notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
           severity="warning", title="t2", body="b2", dedup_key=dedup_key)
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", status="dismissed")
    assert len(rows) == 1
    unread = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    assert len(unread) == 1
    assert unread[0].id != n.id


# --- Stock: low-stock summary -----------------------------------------------


def _make_product(db_session, business_id, *, name):
    product = Product(
        business_id=business_id, sku=None, name=name, cost_price=Decimal("5.00"), sell_price=Decimal("10.00")
    )
    db_session.add(product)
    db_session.flush()
    return product


def test_refresh_low_stock_alerts_creates_a_grouped_summary_notification(db_session, business_id):
    product = _make_product(db_session, business_id, name="Almost Out")
    from datetime import datetime, timezone

    sale = Sale(business_id=business_id, sold_at=datetime.now(timezone.utc), total_amount=Decimal("100.00"))
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            business_id=business_id, sale_id=sale.id, product_id=product.id, quantity=25,
            unit_price=Decimal("4.00"), cost_price_at_sale=Decimal("2.00"),
        )
    )
    InventoryMovementRepository(db_session).create(
        business_id=business_id, product_id=product.id, quantity_delta=5, reason="purchase"
    )
    db_session.commit()

    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product.id})

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="stock")
    assert len(rows) == 1
    assert "1 product" in rows[0].title
    assert rows[0].severity == "warning"

    # Re-running with nothing newly low must not create a second row.
    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product.id})
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="stock")
    assert len(rows) == 1


def test_low_stock_summary_dismisses_itself_once_recovered(db_session, business_id):
    notify_low_stock_summary(db_session, business_id=business_id, low_stock_count=0)
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="stock")
    assert rows == []


# --- Data & Uploads ----------------------------------------------------------


def test_import_completed_success_partial_and_failed_wording(db_session, business_id):
    notify_import_completed(
        db_session, business_id=business_id, import_record_id=uuid.uuid4(), entity_type="sales",
        rows_imported=1284, rows_rejected=0,
    )
    notify_import_completed(
        db_session, business_id=business_id, import_record_id=uuid.uuid4(), entity_type="purchases",
        rows_imported=1238, rows_rejected=14,
    )
    notify_import_completed(
        db_session, business_id=business_id, import_record_id=uuid.uuid4(), entity_type="inventory",
        rows_imported=0, rows_rejected=5,
    )
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="data_uploads")
    by_type = {r.type_key: r for r in rows}
    assert by_type["import_completed"].severity == "success"
    assert "1,284" in by_type["import_completed"].body
    assert by_type["import_partial"].severity == "warning"
    assert "1,238" in by_type["import_partial"].body and "14" in by_type["import_partial"].body
    assert by_type["import_failed"].severity == "critical"


# --- Reports & ORLA Insights --------------------------------------------------


def test_report_ready_and_orla_insights_notifications(db_session, business_id):
    report_id = uuid.uuid4()
    notify_report_ready(
        db_session, business_id=business_id, report_id=report_id, report_type="weekly",
        period_start=date(2026, 8, 3), period_end=date(2026, 8, 9),
    )
    notify_orla_insights(db_session, business_id=business_id, report_id=report_id, recommendation_count=3)
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    report_row = next(r for r in rows if r.category == "reports")
    insight_row = next(r for r in rows if r.category == "orla_insights")
    assert report_row.action_url == f"/reports/{report_id}"
    assert "3 opportunities" in insight_row.title


def test_orla_insights_skips_when_no_recommendations(db_session, business_id):
    notify_orla_insights(db_session, business_id=business_id, report_id=uuid.uuid4(), recommendation_count=0)
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="orla_insights")
    assert rows == []


def test_report_failed_dedups_across_repeated_ticks(db_session, business_id):
    notify_report_failed(db_session, business_id=business_id, report_type="weekly", period_start=date(2026, 8, 3))
    notify_report_failed(db_session, business_id=business_id, report_type="weekly", period_start=date(2026, 8, 3))
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="reports")
    assert len([r for r in rows if r.type_key == "report_failed"]) == 1


# --- Team --------------------------------------------------------------------


def test_add_employee_creates_a_team_notification(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    add_employee(
        db_session, business_id=business_id, business_email="owner@shopa.example", invited_by_user_id="owner-1",
        first_name="Aoife", surname="Byrne", email="aoife@shopa.example", role="staff",
    )
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="team")
    assert any(r.type_key == "employee_added" and "Aoife Byrne" in r.title for r in rows)


def test_role_change_creates_a_security_account_notification(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    seat, _ = add_employee(
        db_session, business_id=business_id, business_email="owner@shopa.example", invited_by_user_id="owner-1",
        first_name="Aoife", surname="Byrne", email="aoife@shopa.example", role="staff",
    )
    update_employee_profile(
        db_session, business_id=business_id, seat_id=seat.id, editing_user_id="owner-1",
        first_name="Aoife", surname="Byrne", role="manager",
        address_line1=None, city=None, postal_code=None, country=None,
    )
    rows = NotificationRepository(db_session).list_for_business(
        business_id, role="owner", category="security_account"
    )
    assert any(r.type_key == "employee_role_changed" and "Manager" in r.body for r in rows)


def test_delete_employee_creates_a_removed_notification(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    seat, _ = add_employee(
        db_session, business_id=business_id, business_email="owner@shopa.example", invited_by_user_id="owner-1",
        first_name="Aoife", surname="Byrne", email="aoife@shopa.example", role="staff",
    )
    delete_employee(db_session, business_id=business_id, seat_id=seat.id, deleting_user_id="owner-1")
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="team")
    assert any(r.type_key == "employee_removed" for r in rows)


def test_try_activate_employee_seat_notifies_once(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    _seed_user(db_session, "staff-1", "aoife@shopa.example")
    seat, _ = add_employee(
        db_session, business_id=business_id, business_email="owner@shopa.example", invited_by_user_id="owner-1",
        first_name="Aoife", surname="Byrne", email="aoife@shopa.example", role="staff",
    )
    from app.repositories.employee_seat import EmployeeSeatRepository

    seats = EmployeeSeatRepository(db_session)
    seats.set_status(seat, "active")
    seats.link_user(seat, "staff-1")
    db_session.commit()

    assert try_activate_employee_seat(db_session, seat) is True
    assert try_activate_employee_seat(db_session, seat) is False  # idempotent — no second Membership/notification
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="team")
    assert len([r for r in rows if r.type_key == "employee_activated"]) == 1


# --- Billing & Branches --------------------------------------------------------


def test_subscription_status_change_is_owner_only_and_categorized_by_branch(db_session, business_id):
    notify_subscription_status_change(
        db_session, business_id=business_id, business_name="Test Business", is_branch=False, new_status="past_due"
    )
    db_session.commit()

    owner_view = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    staff_view = NotificationRepository(db_session).list_for_business(business_id, role="staff")
    assert any(r.category == "billing" and r.severity == "warning" for r in owner_view)
    assert staff_view == []  # billing status is owner-only


def test_subscription_status_change_uses_branches_category_for_a_branch(db_session, business_id):
    notify_subscription_status_change(
        db_session, business_id=business_id, business_name="Galway", is_branch=True, new_status="active"
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="branches")
    assert len(rows) == 1
    assert rows[0].severity == "success"


def test_subscription_status_change_ignores_unrecognized_statuses(db_session, business_id):
    notify_subscription_status_change(
        db_session, business_id=business_id, business_name="Test Business", is_branch=False, new_status="incomplete"
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    assert rows == []


# --- Data freshness ------------------------------------------------------------


def _make_completed_sales_import(db_session, business_id, *, days_ago: int = 0) -> ImportRecord:
    upload = Upload(
        business_id=business_id, storage_key="test/key.csv", original_filename="sales.csv",
        uploaded_by="user-1", status="imported", entity_type="sales",
    )
    db_session.add(upload)
    db_session.flush()
    record = ImportRecord(
        business_id=business_id, upload_id=upload.id, entity_type="sales",
        status="completed", rows_total=1, rows_imported=1, rows_rejected=0,
    )
    db_session.add(record)
    db_session.flush()
    # TimestampMixin's onupdate default only fires when updated_at isn't
    # itself part of the flush's SET clause — setting it explicitly here
    # (to simulate an import completed N days ago) takes precedence.
    record.updated_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.commit()
    return record


def test_freshness_never_uploaded_creates_no_new_data_notification(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="data_uploads")
    assert len(rows) == 1
    assert rows[0].type_key == "no_new_data_detected"
    assert rows[0].severity == "info"


def test_freshness_old_import_creates_data_outdated(db_session, business_id):
    _make_completed_sales_import(db_session, business_id, days_ago=5)
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="data_uploads")
    assert len(rows) == 1
    assert rows[0].type_key == "data_outdated"
    assert rows[0].severity == "warning"
    assert "5 days" in rows[0].body


def test_freshness_recent_import_is_no_new_data_not_yet_outdated(db_session, business_id):
    _make_completed_sales_import(db_session, business_id, days_ago=1)
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="data_uploads")
    assert rows[0].type_key == "no_new_data_detected"


def test_freshness_todays_import_resolves_open_notification(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    assert len(NotificationRepository(db_session).list_for_business(business_id, role="owner")) == 1

    _make_completed_sales_import(db_session, business_id, days_ago=0)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    assert NotificationRepository(db_session).list_for_business(business_id, role="owner") == []
    dismissed = NotificationRepository(db_session).list_for_business(business_id, role="owner", status="dismissed")
    assert len(dismissed) == 1


def test_freshness_rerun_does_not_create_duplicates(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    assert len(rows) == 1


def test_freshness_escalates_type_key_in_place_as_days_pass(db_session, business_id):
    _make_completed_sales_import(db_session, business_id, days_ago=1)
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    first = NotificationRepository(db_session).list_for_business(business_id, role="owner")[0]
    assert first.type_key == "no_new_data_detected"

    # Same underlying (still-1-day-old) record, checked again 3 days
    # later — same open row, escalated classification, not a new row.
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc) + timedelta(days=3))
    db_session.commit()

    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    assert len(rows) == 1
    assert rows[0].id == first.id
    assert rows[0].type_key == "data_outdated"


def test_resolve_data_freshness_clears_open_notification(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    resolve_data_freshness(db_session, business_id=business_id, entity_type="sales")
    db_session.commit()
    assert NotificationRepository(db_session).list_for_business(business_id, role="owner") == []


def test_resolve_data_freshness_ignores_other_entity_types(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    resolve_data_freshness(db_session, business_id=business_id, entity_type="purchases")
    db_session.commit()
    assert len(NotificationRepository(db_session).list_for_business(business_id, role="owner")) == 1


def test_freshness_branch_uses_branch_data_missing_and_names_the_branch(db_session, business_id):
    branch = Business(name="Galway", parent_business_id=business_id, timezone="Europe/Dublin")
    db_session.add(branch)
    db_session.commit()

    check_data_freshness(db_session, business=branch, now=datetime.now(timezone.utc))
    db_session.commit()

    branch_rows = NotificationRepository(db_session).list_for_business(branch.id, role="owner")
    assert branch_rows[0].type_key == "branch_data_missing"
    assert "Galway" in branch_rows[0].title

    # Doesn't leak into the parent's own notification list.
    parent_rows = NotificationRepository(db_session).list_for_business(business_id, role="owner")
    assert parent_rows == []


def test_tick_only_checks_freshness_for_active_subscriptions(db_session, business_id):
    from app.models.subscription import Subscription

    db_session.add(Subscription(business_id=business_id, stripe_customer_id="cus_test_freshness", status="active"))
    db_session.commit()

    summary = run_tick(db_session, now=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc))

    assert summary["freshness_checked"] == 1
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="data_uploads")
    assert any(r.type_key == "no_new_data_detected" for r in rows)


def test_tick_skips_freshness_without_an_active_subscription(db_session, business_id):
    summary = run_tick(db_session, now=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc))

    assert summary["freshness_checked"] == 0
    rows = NotificationRepository(db_session).list_for_business(business_id, role="owner", category="data_uploads")
    assert rows == []
