"""ORLA System status notifications (ORLA Notifications/Security/
Retention prompt, section 3): report-delayed and ORLA-insights-
unavailable. "Upload processing failed"/"upload completed with rejected
rows"/"a scheduled report failed" already have their own coverage
(tests/integration/test_notifications.py) — this file only covers the
two genuinely new signals, plus the scheduler wiring that drives them.
No new incident-tracking model exists — see app/application/
notifications.py's own "ORLA System status" section docstring for why
Notification's existing dedup_key/status mechanism already is one.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.analytics.period import report_generation_moment
from app.application.notifications import (
    is_ai_provider_likely_down,
    notify,
    notify_ai_insights_unavailable,
    notify_report_delayed,
    resolve_report_delayed,
)
from app.models.ai_request import AIRequest
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.ai_request import AIRequestRepository
from app.repositories.notification import NotificationRepository
from app.scheduler.tick import run_tick

_NOW = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)  # a Monday
_LAST_WEEK_START = date(2025, 12, 29)


# --- is_ai_provider_likely_down (pure) ------------------------------------


def test_ai_provider_not_down_with_too_few_samples():
    assert is_ai_provider_likely_down([False, False]) is False


def test_ai_provider_not_down_with_a_mix_of_results():
    assert is_ai_provider_likely_down([False, False, False, False, True]) is False


def test_ai_provider_down_when_every_recent_call_failed():
    assert is_ai_provider_likely_down([False, False, False, False, False]) is True


def test_ai_provider_not_down_with_no_recent_calls_at_all():
    assert is_ai_provider_likely_down([]) is False


# --- notify_ai_insights_unavailable ---------------------------------------


def test_ai_insights_unavailable_notifies_when_down(db_session, business_id):
    notify_ai_insights_unavailable(db_session, business_id=business_id, is_down=True)
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="orla_insights")
    assert len(rows) == 1
    assert rows[0].type_key == "ai_insights_unavailable"
    assert rows[0].severity == "warning"
    # Never leaks a technical exception string — only ever the plain,
    # customer-facing sentence this function itself writes.
    assert "Traceback" not in rows[0].body
    assert "Exception" not in rows[0].body


def test_ai_insights_unavailable_silently_clears_when_recovered(db_session, business_id):
    notify_ai_insights_unavailable(db_session, business_id=business_id, is_down=True)
    db_session.commit()
    notify_ai_insights_unavailable(db_session, business_id=business_id, is_down=False)
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert rows == []


def test_ai_insights_unavailable_reprocessing_does_not_duplicate(db_session, business_id):
    notify_ai_insights_unavailable(db_session, business_id=business_id, is_down=True)
    db_session.commit()
    notify_ai_insights_unavailable(db_session, business_id=business_id, is_down=True)
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert len(rows) == 1


# --- notify_report_delayed / resolve_report_delayed ------------------------


def test_report_delayed_notifies(db_session, business_id):
    notify_report_delayed(db_session, business_id=business_id, report_type="weekly", period_start=_LAST_WEEK_START)
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="reports")
    assert len(rows) == 1
    assert rows[0].type_key == "report_delayed"
    assert rows[0].severity == "warning"


def test_resolve_report_delayed_clears_it(db_session, business_id):
    notify_report_delayed(db_session, business_id=business_id, report_type="weekly", period_start=_LAST_WEEK_START)
    db_session.commit()
    resolve_report_delayed(db_session, business_id=business_id, report_type="weekly", period_start=_LAST_WEEK_START)
    db_session.commit()
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner")
    assert rows == []


# --- app/analytics/period.py::report_generation_moment ---------------------


def test_report_generation_moment_is_8am_the_day_after_period_end():
    moment = report_generation_moment("Europe/Dublin", date(2026, 1, 4))  # a Sunday
    assert moment.date() == date(2026, 1, 5)  # the Monday after
    assert moment.hour == 8


# --- Active-incidents banner (list_active_incidents) ------------------------


def test_list_active_incidents_includes_only_system_status_type_keys(db_session, business_id):
    notify_report_delayed(db_session, business_id=business_id, report_type="weekly", period_start=_LAST_WEEK_START)
    # A completely unrelated notification type — must never show up in
    # the banner query, only in the ordinary Notification Centre.
    notify(
        db_session, business_id=business_id, category="team", type_key="employee_added",
        severity="info", title="A", body="a",
    )
    db_session.commit()

    incidents = NotificationRepository(db_session).list_active_incidents(business_id, role="owner")
    assert len(incidents) == 1
    assert incidents[0].type_key == "report_delayed"


def test_list_active_incidents_excludes_dismissed(db_session, business_id):
    notify_report_delayed(db_session, business_id=business_id, report_type="weekly", period_start=_LAST_WEEK_START)
    db_session.commit()
    resolve_report_delayed(db_session, business_id=business_id, report_type="weekly", period_start=_LAST_WEEK_START)
    db_session.commit()

    incidents = NotificationRepository(db_session).list_active_incidents(business_id, role="owner")
    assert incidents == []


# --- Scheduler wiring --------------------------------------------------


def _make_product(db_session, business_id, *, name="Chain Lube"):
    product = Product(business_id=business_id, sku=None, name=name, cost_price=Decimal("5.00"), sell_price=Decimal("10.00"))
    db_session.add(product)
    db_session.flush()
    return product


def _seed_ai_requests(db_session, business_id, *, count, success):
    for _ in range(count):
        db_session.add(
            AIRequest(business_id=business_id, user_id="user-1", lane="business_qa", provider="openrouter", model="test", success=success)
        )
    db_session.commit()


def test_tick_notifies_ai_unavailable_when_recent_platform_wide_calls_all_failed(db_session, business_id):
    _seed_ai_requests(db_session, business_id, count=5, success=False)
    from app.models.subscription import Subscription

    db_session.add(Subscription(business_id=business_id, stripe_customer_id="cus_ai_test", status="active"))
    db_session.commit()

    run_tick(db_session, now=_NOW)

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="orla_insights")
    assert any(r.type_key == "ai_insights_unavailable" for r in rows)


def test_tick_does_not_notify_ai_unavailable_when_recent_calls_mostly_succeeded(db_session, business_id):
    _seed_ai_requests(db_session, business_id, count=4, success=True)
    _seed_ai_requests(db_session, business_id, count=1, success=False)
    from app.models.subscription import Subscription

    db_session.add(Subscription(business_id=business_id, stripe_customer_id="cus_ai_test2", status="active"))
    db_session.commit()

    run_tick(db_session, now=_NOW)

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="orla_insights")
    assert not any(r.type_key == "ai_insights_unavailable" for r in rows)


def test_tick_flags_a_report_still_incomplete_well_past_its_due_moment(db_session, business_id, monkeypatch):
    import app.scheduler.tick as tick_module
    from app.models.report import Report

    # A weekly report row still "failed" but under MAX_ATTEMPTS, created
    # long enough ago that it's past REPORT_DELAYED_AFTER_HOURS relative
    # to its own due generation moment (2026-01-05 08:00 Dublin).
    period_start_dt = datetime(2025, 12, 29, tzinfo=timezone.utc)
    period_end_dt = datetime(2026, 1, 5, tzinfo=timezone.utc)
    db_session.add(
        Report(
            business_id=business_id, report_type="weekly", period_start=period_start_dt, period_end=period_end_dt,
            status="failed", attempts=1, last_error="transient",
        )
    )
    db_session.commit()

    # This retry attempt fails again too — otherwise a real successful
    # generation would immediately supersede/clear the "delayed" notice
    # within the very same tick (correct real behaviour, but not what
    # this test is isolating: whether the delay check itself fires).
    def _always_fails_again(db, *, business_id, report_type, now):
        report = db.query(Report).filter_by(business_id=business_id, report_type=report_type).one()
        report.attempts += 1
        report.last_error = "transient"
        db.flush()
        return report

    monkeypatch.setattr(tick_module, "generate_report", _always_fails_again)

    # 6 hours after the due moment — past REPORT_DELAYED_AFTER_HOURS (4).
    later = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
    run_tick(db_session, now=later)

    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="reports")
    assert any(r.type_key == "report_delayed" for r in rows)
