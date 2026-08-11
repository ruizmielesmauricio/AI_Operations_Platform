"""Weekly Business Performance (section 1) and consolidated Monday Stock
Review (section 2) notifications — ORLA Notifications/Security/Retention
prompt. app/application/notifications.py's notify_weekly_business_
performance/notify_stock_review functions are tested directly (they take
already-computed inputs, matching every other notify_* function's own
"formats a number a call site already has" contract); app/application/
stock_review.py::get_stock_review and the scheduler wiring are tested
against a real (SQLite) database.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.application.notifications import notify_stock_review, notify_weekly_business_performance
from app.application.stock_review import get_stock_review
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.notification import NotificationRepository
from app.scheduler.tick import run_tick

# 2026-01-05 is a Monday — matches test_report_generation.py's own fixture
# date, so a weekly report is genuinely due at this "now".
_NOW = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
_LAST_WEEK_START = date(2025, 12, 29)


def _make_product(db_session, business_id, *, name="Chain Lube", threshold_days=None):
    product = Product(
        business_id=business_id, sku=None, name=name, cost_price=Decimal("5.00"), sell_price=Decimal("10.00"),
        low_stock_threshold_days=threshold_days,
    )
    db_session.add(product)
    db_session.flush()
    return product


# --- notify_weekly_business_performance --------------------------------


def test_weekly_performance_silent_without_enough_history(db_session, business_id):
    notify_weekly_business_performance(
        db_session, business_id=business_id, report_id=uuid.uuid4(), period_start=_LAST_WEEK_START,
        revenue_current=Decimal("2000"), revenue_previous=Decimal("1000"), revenue_change_pct=Decimal("100"),
        earliest_sale_date=_LAST_WEEK_START - timedelta(days=7),  # only 1 week of history, not 4
    )
    db_session.commit()
    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []


def test_weekly_performance_silent_when_change_pct_is_unknown(db_session, business_id):
    notify_weekly_business_performance(
        db_session, business_id=business_id, report_id=uuid.uuid4(), period_start=_LAST_WEEK_START,
        revenue_current=Decimal("1000"), revenue_previous=Decimal("0"), revenue_change_pct=None,
        earliest_sale_date=_LAST_WEEK_START - timedelta(days=60),
    )
    db_session.commit()
    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []


def test_weekly_performance_silent_below_materiality_threshold(db_session, business_id):
    notify_weekly_business_performance(
        db_session, business_id=business_id, report_id=uuid.uuid4(), period_start=_LAST_WEEK_START,
        revenue_current=Decimal("1020"), revenue_previous=Decimal("1000"), revenue_change_pct=Decimal("2"),
        earliest_sale_date=_LAST_WEEK_START - timedelta(days=60),
    )
    db_session.commit()
    assert NotificationRepository(db_session).list_items_for_business(business_id, role="owner") == []


def test_weekly_performance_notifies_on_a_material_increase(db_session, business_id):
    report_id = uuid.uuid4()
    notify_weekly_business_performance(
        db_session, business_id=business_id, report_id=report_id, period_start=_LAST_WEEK_START,
        revenue_current=Decimal("2000"), revenue_previous=Decimal("1000"), revenue_change_pct=Decimal("100"),
        earliest_sale_date=_LAST_WEEK_START - timedelta(days=60),
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="reports")
    assert len(rows) == 1
    assert rows[0].type_key == "weekly_performance"
    assert "increased" in rows[0].title
    assert rows[0].severity == "success"
    assert rows[0].action_url == f"/reports/{report_id}"


def test_weekly_performance_notifies_on_a_material_decline_with_warning_severity(db_session, business_id):
    notify_weekly_business_performance(
        db_session, business_id=business_id, report_id=uuid.uuid4(), period_start=_LAST_WEEK_START,
        revenue_current=Decimal("500"), revenue_previous=Decimal("1000"), revenue_change_pct=Decimal("-50"),
        earliest_sale_date=_LAST_WEEK_START - timedelta(days=60),
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="reports")
    assert rows[0].type_key == "weekly_performance"
    assert "declined" in rows[0].title
    assert rows[0].severity == "warning"


def test_weekly_performance_rerun_for_the_same_week_updates_not_duplicates(db_session, business_id):
    kwargs = dict(
        business_id=business_id, report_id=uuid.uuid4(), period_start=_LAST_WEEK_START,
        earliest_sale_date=_LAST_WEEK_START - timedelta(days=60),
    )
    notify_weekly_business_performance(
        db_session, revenue_current=Decimal("2000"), revenue_previous=Decimal("1000"),
        revenue_change_pct=Decimal("100"), **kwargs,
    )
    db_session.commit()
    notify_weekly_business_performance(
        db_session, revenue_current=Decimal("2100"), revenue_previous=Decimal("1000"),
        revenue_change_pct=Decimal("110"), **kwargs,
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="reports")
    assert len(rows) == 1
    assert "110" in rows[0].title


# --- notify_stock_review -------------------------------------------------


def test_stock_review_complete_when_nothing_to_flag(db_session, business_id):
    notify_stock_review(
        db_session, business_id=business_id, week_start=_LAST_WEEK_START,
        out_of_stock_count=0, stale_count=0, excess_count=0,
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="stock")
    assert len(rows) == 1
    assert rows[0].type_key == "stock_review_complete"
    assert rows[0].severity == "success"


def test_stock_review_summarizes_all_three_counts(db_session, business_id):
    notify_stock_review(
        db_session, business_id=business_id, week_start=_LAST_WEEK_START,
        out_of_stock_count=4, stale_count=7, excess_count=3,
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="stock")
    assert len(rows) == 1
    assert rows[0].type_key == "stock_review"
    body = rows[0].body
    assert "4" in body and "out of stock" in body
    assert "7" in body and "stale" in body
    assert "3" in body and "overstocked" in body
    # No per-product list — only concise counts (the prompt's own
    # explicit "do not place full product lists in the notification").
    assert "Chain Lube" not in body


def test_stock_review_links_to_the_most_urgent_nonzero_filter(db_session, business_id):
    out_of_stock = notify_stock_review(
        db_session, business_id=business_id, week_start=_LAST_WEEK_START,
        out_of_stock_count=1, stale_count=5, excess_count=5,
    )
    db_session.commit()
    row = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="stock")[0]
    assert row.action_url == "/products?stock_filter=out_of_stock"


def test_stock_review_reprocessing_the_same_week_does_not_duplicate(db_session, business_id):
    notify_stock_review(
        db_session, business_id=business_id, week_start=_LAST_WEEK_START,
        out_of_stock_count=1, stale_count=0, excess_count=0,
    )
    db_session.commit()
    notify_stock_review(
        db_session, business_id=business_id, week_start=_LAST_WEEK_START,
        out_of_stock_count=2, stale_count=0, excess_count=0,
    )
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="stock")
    assert len(rows) == 1
    assert "2" in rows[0].body


# --- get_stock_review (real DB orchestration) -----------------------------


def test_get_stock_review_counts_a_real_out_of_stock_product(db_session, business_id):
    product = _make_product(db_session, business_id)
    db_session.add(
        InventoryMovement(business_id=business_id, product_id=product.id, quantity_delta=0, reason="adjustment", event_date=date(2026, 1, 1))
    )
    db_session.commit()

    result = get_stock_review(db_session, business_id=business_id)
    assert result.out_of_stock_count == 1


def test_get_stock_review_counts_a_real_excess_product_against_its_own_threshold(db_session, business_id):
    # A product with a 7-day threshold, selling very slowly (1 unit in the
    # last 30 days) against a large stock pile — cover_days far exceeds
    # 3x the threshold.
    product = _make_product(db_session, business_id, threshold_days=Decimal("7"))
    sold_at = datetime.combine(date(2026, 1, 1), time.min, tzinfo=timezone.utc)
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=Decimal("10.00"))
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(business_id=business_id, sale_id=sale.id, product_id=product.id, quantity=1, unit_price=Decimal("10.00"))
    )
    db_session.add(
        InventoryMovement(business_id=business_id, product_id=product.id, quantity_delta=1000, reason="purchase", event_date=date(2026, 1, 1))
    )
    db_session.commit()

    result = get_stock_review(db_session, business_id=business_id, now=_NOW)
    assert result.excess_count == 1


# --- Scheduler wiring ------------------------------------------------------


def test_tick_wires_weekly_performance_and_stock_review_only_for_weekly_reports(db_session, business_id):
    product = _make_product(db_session, business_id)
    for offset in range(7):
        sold_at = datetime.combine(_LAST_WEEK_START + timedelta(days=offset), time.min, tzinfo=timezone.utc)
        sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=Decimal("20.00"))
        db_session.add(sale)
        db_session.flush()
        db_session.add(
            SaleItem(business_id=business_id, sale_id=sale.id, product_id=product.id, quantity=2, unit_price=Decimal("10.00"))
        )
        db_session.add(
            InventoryMovement(business_id=business_id, product_id=product.id, quantity_delta=-2, reason="sale", event_date=_LAST_WEEK_START + timedelta(days=offset))
        )
    db_session.commit()

    run_tick(db_session, now=_NOW)

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    type_keys = {r.type_key for r in rows}
    # Stock review always fires (even the "complete" no-op message) once a
    # weekly report succeeds — proves the wiring reached that branch.
    assert "stock_review_complete" in type_keys or "stock_review" in type_keys
    # No monthly-report-triggered duplicate of either — a monthly report
    # was also due in this same tick (2026-01-05 is the 1st weekday of a
    # new month too), and the "if report_type == weekly" gate must have
    # kept these notifications from firing a second time under a
    # different dedup_key for the monthly pass.
    stock_review_rows = [r for r in rows if r.type_key in ("stock_review", "stock_review_complete")]
    assert len(stock_review_rows) == 1
