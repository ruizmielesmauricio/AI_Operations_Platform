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
    InvalidNotificationDateFilter,
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
    resolve_notification_date_range,
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

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert len(rows) == 2


def test_notify_with_dedup_key_updates_the_existing_open_row(db_session, business_id):
    dedup_key = f"low_stock_summary:{business_id}"
    notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
           severity="warning", title="3 products below reorder point", body="...", dedup_key=dedup_key)
    db_session.commit()

    notify(db_session, business_id=business_id, category="stock", type_key="low_stock_summary",
           severity="warning", title="5 products below reorder point", body="updated", dedup_key=dedup_key)
    db_session.commit()

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
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

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", status="dismissed")
    assert len(rows) == 1
    unread = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
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

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="stock")
    assert len(rows) == 1
    assert "1 product" in rows[0].title
    assert rows[0].severity == "warning"

    # Re-running with nothing newly low must not create a second row.
    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product.id})
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="stock")
    assert len(rows) == 1


def test_low_stock_summary_dismisses_itself_once_recovered(db_session, business_id):
    notify_low_stock_summary(db_session, business_id=business_id, low_stock_count=0)
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="stock")
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

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
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

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    report_row = next(r for r in rows if r.category == "reports")
    insight_row = next(r for r in rows if r.category == "orla_insights")
    assert report_row.action_url == f"/reports/{report_id}"
    assert "3 opportunities" in insight_row.title


def test_orla_insights_skips_when_no_recommendations(db_session, business_id):
    notify_orla_insights(db_session, business_id=business_id, report_id=uuid.uuid4(), recommendation_count=0)
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="orla_insights")
    assert rows == []


def test_report_failed_dedups_across_repeated_ticks(db_session, business_id):
    notify_report_failed(db_session, business_id=business_id, report_type="weekly", period_start=date(2026, 8, 3))
    notify_report_failed(db_session, business_id=business_id, report_type="weekly", period_start=date(2026, 8, 3))
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="reports")
    assert len([r for r in rows if r.type_key == "report_failed"]) == 1


# --- Team --------------------------------------------------------------------


def test_add_employee_creates_a_team_notification(db_session, business_id):
    _seed_user(db_session, "owner-1", "owner@shopa.example")
    add_employee(
        db_session, business_id=business_id, business_email="owner@shopa.example", invited_by_user_id="owner-1",
        first_name="Aoife", surname="Byrne", email="aoife@shopa.example", role="staff",
    )
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="team")
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
    rows = NotificationRepository(db_session).list_items_for_business(
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
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="team")
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

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="team")
    assert len([r for r in rows if r.type_key == "employee_activated"]) == 1


# --- Billing & Branches --------------------------------------------------------


def test_subscription_status_change_is_owner_only_and_categorized_by_branch(db_session, business_id):
    notify_subscription_status_change(
        db_session, business_id=business_id, business_name="Test Business", is_branch=False, new_status="past_due"
    )
    db_session.commit()

    owner_view = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    staff_view = NotificationRepository(db_session).list_items_for_business(business_id, role="staff")
    assert any(r.category == "billing" and r.severity == "warning" for r in owner_view)
    assert staff_view == []  # billing status is owner-only


def test_subscription_status_change_uses_branches_category_for_a_branch(db_session, business_id):
    notify_subscription_status_change(
        db_session, business_id=business_id, business_name="Galway", is_branch=True, new_status="active"
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="branches")
    assert len(rows) == 1
    assert rows[0].severity == "success"


def test_subscription_status_change_ignores_unrecognized_statuses(db_session, business_id):
    notify_subscription_status_change(
        db_session, business_id=business_id, business_name="Test Business", is_branch=False, new_status="incomplete"
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
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
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert len(rows) == 1
    assert rows[0].type_key == "no_new_data_detected"
    assert rows[0].severity == "info"


def test_freshness_old_import_creates_data_outdated(db_session, business_id):
    _make_completed_sales_import(db_session, business_id, days_ago=5)
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert len(rows) == 1
    assert rows[0].type_key == "data_outdated"
    assert rows[0].severity == "warning"
    assert "5 days" in rows[0].body


def test_freshness_recent_import_is_no_new_data_not_yet_outdated(db_session, business_id):
    _make_completed_sales_import(db_session, business_id, days_ago=1)
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert rows[0].type_key == "no_new_data_detected"


def test_freshness_todays_import_resolves_open_notification(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    assert len(NotificationRepository(db_session).list_items_for_business(business_id, role="owner")) == 1

    _make_completed_sales_import(db_session, business_id, days_ago=0)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []
    dismissed = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", status="dismissed")
    assert len(dismissed) == 1


def test_freshness_migrates_a_pre_existing_legacy_dedup_key_notification(db_session, business_id):
    """Live-found real bug: a business with an open freshness
    notification created under the old, sales-only dedup_key format
    (before the multi-dataset consolidation redesign) got a *second*,
    duplicate notification on the next tick, because the new consolidated
    key never matched the old one — exactly the daily-duplicate spam this
    whole feature exists to prevent. Regression guard: simulate that
    exact pre-existing state (a notify() call using the literal old key
    string, bypassing the current dedup_key helper entirely, the same
    way a row created by last week's code would already be sitting in a
    real database) and confirm a fresh check_data_freshness call collapses
    it into one row, not two."""
    business = db_session.get(Business, business_id)
    legacy_key = f"data_freshness:{business_id}:sales"
    notify(
        db_session, business_id=business_id, category="data_uploads", type_key="no_new_data_detected",
        severity="info", title="No new sales data today",
        body="We have not received new sales data today. Update your data so ORLA can keep your insights current.",
        action_label="Upload sales data", action_url="/uploads", dedup_key=legacy_key,
    )
    db_session.commit()
    assert len(NotificationRepository(db_session).list_items_for_business(business_id, role="owner")) == 1

    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    # Exactly one open row afterward — the legacy one was folded away,
    # not left sitting alongside a new duplicate.
    open_rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert len(open_rows) == 1
    assert open_rows[0].type_key == "no_new_data_detected"


def test_freshness_rerun_does_not_create_duplicates(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert len(rows) == 1


def test_freshness_escalates_type_key_in_place_as_days_pass(db_session, business_id):
    _make_completed_sales_import(db_session, business_id, days_ago=1)
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    first = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")[0]
    assert first.type_key == "no_new_data_detected"

    # Same underlying (still-1-day-old) record, checked again 3 days
    # later — same open row, escalated classification, not a new row.
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc) + timedelta(days=3))
    db_session.commit()

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert len(rows) == 1
    assert rows[0].id == first.id
    assert rows[0].type_key == "data_outdated"


def test_resolve_data_freshness_clears_open_notification(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    assert len(NotificationRepository(db_session).list_items_for_business(business_id, role="owner")) == 1

    # Recomputes from scratch (see resolve_data_freshness's own docstring)
    # rather than blindly dismissing, so — matching real usage from
    # app/imports/importer.py — a fresh import actually has to exist for
    # this to clear the notification.
    _make_completed_sales_import(db_session, business_id, days_ago=0)
    resolve_data_freshness(db_session, business_id=business_id, entity_type="sales")
    db_session.commit()
    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []


def test_resolve_data_freshness_ignores_other_entity_types(db_session, business_id):
    business = db_session.get(Business, business_id)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    resolve_data_freshness(db_session, business_id=business_id, entity_type="purchases")
    db_session.commit()
    assert len(NotificationRepository(db_session).list_items_for_business(business_id, role="owner")) == 1


def test_freshness_branch_uses_branch_data_missing_and_names_the_branch(db_session, business_id):
    branch = Business(name="Galway", parent_business_id=business_id, timezone="Europe/Dublin")
    db_session.add(branch)
    db_session.commit()

    check_data_freshness(db_session, business=branch, now=datetime.now(timezone.utc))
    db_session.commit()

    branch_rows = NotificationRepository(db_session).list_items_for_business(branch.id, role="owner")
    assert branch_rows[0].type_key == "branch_data_missing"
    assert "Galway" in branch_rows[0].title

    # Doesn't leak into the parent's own notification list.
    parent_rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert parent_rows == []


def test_tick_only_checks_freshness_for_active_subscriptions(db_session, business_id):
    from app.models.subscription import Subscription

    db_session.add(Subscription(business_id=business_id, stripe_customer_id="cus_test_freshness", status="active"))
    db_session.commit()

    summary = run_tick(db_session, now=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc))

    assert summary["freshness_checked"] == 1
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert any(r.type_key == "no_new_data_detected" for r in rows)


def test_tick_skips_freshness_without_an_active_subscription(db_session, business_id):
    summary = run_tick(db_session, now=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc))

    assert summary["freshness_checked"] == 0
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert rows == []


# --- Data freshness: purchases/inventory/repairs (extends the sales-only
# design above to every entity type app/imports/aliases.py's SUPPORTED_
# ENTITY_TYPES actually supports) ------------------------------------------


def _make_completed_import(db_session, business_id, entity_type, *, days_ago: int = 0) -> ImportRecord:
    upload = Upload(
        business_id=business_id, storage_key=f"test/{entity_type}.csv", original_filename=f"{entity_type}.csv",
        uploaded_by="user-1", status="imported", entity_type=entity_type,
    )
    db_session.add(upload)
    db_session.flush()
    record = ImportRecord(
        business_id=business_id, upload_id=upload.id, entity_type=entity_type,
        status="completed", rows_total=1, rows_imported=1, rows_rejected=0,
    )
    db_session.add(record)
    db_session.flush()
    record.updated_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.commit()
    return record


def test_freshness_never_used_dataset_is_never_flagged(db_session, business_id):
    """A business that's never once imported purchases/inventory/repairs
    gets no nudge about them at all — only sales is unconditionally
    expected; the other three are only "used" once evidenced by a real
    completed import."""
    business = db_session.get(Business, business_id)
    _make_completed_import(db_session, business_id, "sales", days_ago=0)  # sales itself fresh
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []


def test_freshness_flags_stale_purchases_once_business_has_used_it(db_session, business_id):
    business = db_session.get(Business, business_id)
    _make_completed_import(db_session, business_id, "sales", days_ago=0)
    _make_completed_import(db_session, business_id, "purchases", days_ago=20)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert len(rows) == 1
    assert rows[0].type_key == "datasets_outdated"
    assert rows[0].severity == "warning"
    assert "Purchases" in rows[0].body


def test_freshness_purchases_within_sparse_cadence_is_not_flagged(db_session, business_id):
    """Purchases/inventory/repairs get a much looser cadence than sales
    (14 days, not 3) — a shop doesn't take a delivery every day."""
    business = db_session.get(Business, business_id)
    _make_completed_import(db_session, business_id, "sales", days_ago=0)
    _make_completed_import(db_session, business_id, "purchases", days_ago=10)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []


def test_freshness_consolidates_sales_and_another_stale_dataset_into_one_notification(db_session, business_id):
    business = db_session.get(Business, business_id)
    _make_completed_import(db_session, business_id, "sales", days_ago=5)
    _make_completed_import(db_session, business_id, "inventory", days_ago=20)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    # One consolidated notification, not two.
    assert len(rows) == 1
    assert rows[0].type_key == "data_outdated"  # sales still drives the primary type_key
    assert "5 days" in rows[0].body
    assert "Inventory" in rows[0].body


def test_freshness_a_stale_dataset_does_not_prevent_sales_from_showing_fresh(db_session, business_id):
    business = db_session.get(Business, business_id)
    _make_completed_import(db_session, business_id, "sales", days_ago=0)
    _make_completed_import(db_session, business_id, "repairs", days_ago=30)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert len(rows) == 1
    assert rows[0].type_key == "datasets_outdated"
    assert "Repairs" in rows[0].body
    # Sales itself is never named as the problem here.
    assert "Sales" not in rows[0].body.split(".")[0]


def test_freshness_resolves_fully_once_every_used_dataset_is_fresh_again(db_session, business_id):
    business = db_session.get(Business, business_id)
    _make_completed_import(db_session, business_id, "sales", days_ago=5)
    _make_completed_import(db_session, business_id, "purchases", days_ago=20)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    assert len(NotificationRepository(db_session).list_items_for_business(business_id, role="owner")) == 1

    # Both datasets catch up.
    _make_completed_import(db_session, business_id, "sales", days_ago=0)
    _make_completed_import(db_session, business_id, "purchases", days_ago=0)
    resolve_data_freshness(db_session, business_id=business_id, entity_type="purchases")
    db_session.commit()
    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []


def test_freshness_resolving_one_dataset_updates_but_does_not_fully_clear_when_another_is_still_stale(
    db_session, business_id
):
    business = db_session.get(Business, business_id)
    _make_completed_import(db_session, business_id, "sales", days_ago=5)
    _make_completed_import(db_session, business_id, "purchases", days_ago=20)
    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    original = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")[0]
    assert "Purchases" in original.body

    # Only sales catches up — purchases stays stale.
    _make_completed_import(db_session, business_id, "sales", days_ago=0)
    resolve_data_freshness(db_session, business_id=business_id, entity_type="sales")
    db_session.commit()

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert len(rows) == 1
    assert rows[0].id == original.id  # same row, updated in place — not dismissed and recreated
    assert rows[0].type_key == "datasets_outdated"  # sales no longer drives the message
    assert "Purchases" in rows[0].body


def test_freshness_failed_import_does_not_count_as_fresh(db_session, business_id):
    """A failed (not completed) import must never satisfy freshness — only
    ImportRecordRepository.latest_completed_by_entity_type's own
    status == "completed" filter is ever consulted, so a failed row is
    already structurally invisible to this check; asserted directly here
    as a regression guard."""
    business = db_session.get(Business, business_id)
    upload = Upload(
        business_id=business_id, storage_key="test/failed.csv", original_filename="failed.csv",
        uploaded_by="user-1", status="imported", entity_type="sales",
    )
    db_session.add(upload)
    db_session.flush()
    db_session.add(
        ImportRecord(
            business_id=business_id, upload_id=upload.id, entity_type="sales",
            status="failed", rows_total=1, rows_imported=0, rows_rejected=1,
        )
    )
    db_session.commit()

    check_data_freshness(db_session, business=business, now=datetime.now(timezone.utc))
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="data_uploads")
    assert len(rows) == 1
    assert rows[0].type_key == "no_new_data_detected"  # still treated as "never uploaded", not fresh


# --- Pagination --------------------------------------------------------------


def _seed_n_notifications(db_session, business_id, count):
    for i in range(count):
        notify(
            db_session, business_id=business_id, category="team", type_key="employee_added",
            severity="info", title=f"Notification {i}", body="body",
        )
    db_session.commit()


def test_list_for_business_returns_total_alongside_the_page(db_session, business_id):
    _seed_n_notifications(db_session, business_id, 5)
    items, total = NotificationRepository(db_session).list_for_business(business_id, role="owner", limit=2, offset=0)
    assert len(items) == 2
    assert total == 5


def test_list_for_business_pages_do_not_overlap(db_session, business_id):
    _seed_n_notifications(db_session, business_id, 5)
    repo = NotificationRepository(db_session)
    page1, _ = repo.list_for_business(business_id, role="owner", limit=2, offset=0)
    page2, _ = repo.list_for_business(business_id, role="owner", limit=2, offset=2)
    page3, _ = repo.list_for_business(business_id, role="owner", limit=2, offset=4)
    ids = [n.id for n in page1 + page2 + page3]
    assert len(ids) == len(set(ids)) == 5  # every row appears exactly once across all pages


def test_list_for_business_ordering_is_deterministic_across_calls(db_session, business_id):
    _seed_n_notifications(db_session, business_id, 5)
    repo = NotificationRepository(db_session)
    first_call, _ = repo.list_for_business(business_id, role="owner", limit=5, offset=0)
    second_call, _ = repo.list_for_business(business_id, role="owner", limit=5, offset=0)
    assert [n.id for n in first_call] == [n.id for n in second_call]


# --- Date-range filtering ------------------------------------------------


def test_resolve_notification_date_range_none_when_no_filter_given(db_session):
    assert resolve_notification_date_range(
        "Europe/Dublin", date_filter=None, start_date=None, end_date=None, now=datetime.now(timezone.utc)
    ) is None


def test_resolve_notification_date_range_today_is_one_day_wide(db_session):
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    start, end = resolve_notification_date_range(
        "Europe/Dublin", date_filter="today", start_date=None, end_date=None, now=now
    )
    assert (end - start).days == 1


def test_resolve_notification_date_range_7d_is_seven_days_wide(db_session):
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    start, end = resolve_notification_date_range(
        "Europe/Dublin", date_filter="7d", start_date=None, end_date=None, now=now
    )
    assert (end - start).days == 7


def test_resolve_notification_date_range_custom_requires_both_dates(db_session):
    with pytest.raises(InvalidNotificationDateFilter):
        resolve_notification_date_range(
            "Europe/Dublin", date_filter="custom", start_date=date(2026, 1, 1), end_date=None,
            now=datetime.now(timezone.utc),
        )


def test_resolve_notification_date_range_rejects_reversed_range(db_session):
    with pytest.raises(InvalidNotificationDateFilter):
        resolve_notification_date_range(
            "Europe/Dublin", date_filter="custom", start_date=date(2026, 1, 10), end_date=date(2026, 1, 1),
            now=datetime.now(timezone.utc),
        )


def test_resolve_notification_date_range_rejects_excessive_range(db_session):
    with pytest.raises(InvalidNotificationDateFilter):
        resolve_notification_date_range(
            "Europe/Dublin", date_filter="custom", start_date=date(2020, 1, 1), end_date=date(2026, 1, 1),
            now=datetime.now(timezone.utc),
        )


def test_resolve_notification_date_range_rejects_dates_without_custom(db_session):
    with pytest.raises(InvalidNotificationDateFilter):
        resolve_notification_date_range(
            "Europe/Dublin", date_filter="today", start_date=date(2026, 1, 1), end_date=None,
            now=datetime.now(timezone.utc),
        )


def test_resolve_notification_date_range_accepts_valid_custom_range(db_session):
    start, end = resolve_notification_date_range(
        "Europe/Dublin", date_filter="custom", start_date=date(2026, 1, 1), end_date=date(2026, 1, 7),
        now=datetime.now(timezone.utc),
    )
    assert (end - start).days == 7  # inclusive both ends


def test_list_for_business_date_range_filters_out_notifications_outside_it(db_session, business_id):
    n = notify(
        db_session, business_id=business_id, category="team", type_key="employee_added",
        severity="info", title="Old", body="body",
    )
    db_session.commit()
    n.created_at = datetime.now(timezone.utc) - timedelta(days=60)
    db_session.commit()

    notify(
        db_session, business_id=business_id, category="team", type_key="employee_added",
        severity="info", title="Recent", body="body",
    )
    db_session.commit()

    business = db_session.get(Business, business_id)
    start, end = resolve_notification_date_range(
        business.timezone, date_filter="30d", start_date=None, end_date=None, now=datetime.now(timezone.utc)
    )
    items, total = NotificationRepository(db_session).list_for_business(
        business_id, role="owner", start_at=start, end_at=end
    )
    assert total == 1
    assert items[0].title == "Recent"


def test_unread_count_is_not_affected_by_the_requests_own_date_filter(db_session, business_id):
    """unread_count always reflects the caller's full, role-scoped unread
    total — never re-filtered by whatever date range the current request
    happens to be browsing (see NotificationListOut's own docstring)."""
    n = notify(
        db_session, business_id=business_id, category="team", type_key="employee_added",
        severity="info", title="Old unread", body="body",
    )
    db_session.commit()
    n.created_at = datetime.now(timezone.utc) - timedelta(days=90)
    db_session.commit()

    business = db_session.get(Business, business_id)
    start, end = resolve_notification_date_range(
        business.timezone, date_filter="today", start_date=None, end_date=None, now=datetime.now(timezone.utc)
    )
    repo = NotificationRepository(db_session)
    items, total = repo.list_for_business(business_id, role="owner", start_at=start, end_at=end)
    unread_count = repo.count_unread(business_id, role="owner")

    assert total == 0  # nothing in "today"
    assert unread_count == 1  # but the old unread notification still counts
