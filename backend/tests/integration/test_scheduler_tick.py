"""Stage D17/D18 — verifies app/scheduler/tick.py's reconciliation logic
(which of PR-8.1/8.2's scheduling, PR-8.9's retry, and PR-8.10's recovery
actually fire) against a real (SQLite) database.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.application.weather_ingestion import SNAPSHOT_HOUR_LOCAL
from app.models.business import Business
from app.models.report import Report
from app.models.subscription import Subscription
from app.repositories.notification import NotificationRepository
from app.repositories.report import MAX_ATTEMPTS, ReportRepository
from app.repositories.weather_observation import WeatherObservationRepository
from app.scheduler.tick import run_tick
from app.weather import client as weather_client
from app.weather.client import DailyForecast
from app.weather.exceptions import WeatherProviderError

# A Monday, 08:00 exactly — the weekly generation moment for the previous
# completed week. January in Dublin (the default business timezone) is
# GMT, no DST offset to account for.
_MONDAY_0800 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
# Same Monday, but past the weather snapshot's own later local-time gate
# (app/application/weather_ingestion.py::SNAPSHOT_HOUR_LOCAL).
_MONDAY_PAST_SNAPSHOT_HOUR = datetime(2026, 1, 5, SNAPSHOT_HOUR_LOCAL + 1, 0, tzinfo=timezone.utc)


def test_tick_generates_a_due_missing_report(db_session, business_id):
    summary = run_tick(db_session, now=_MONDAY_0800)

    assert summary["generated"] >= 1
    reports = ReportRepository(db_session).list_active_for_business(business_id, now=_MONDAY_0800)
    assert any(r.report_type == "weekly" for r in reports)


def test_tick_leaves_an_already_completed_report_alone(db_session, business_id):
    run_tick(db_session, now=_MONDAY_0800)
    first_pass_reports = ReportRepository(db_session).list_active_for_business(business_id, now=_MONDAY_0800)
    weekly_report = next(r for r in first_pass_reports if r.report_type == "weekly")
    first_generated_at = weekly_report.updated_at

    summary = run_tick(db_session, now=_MONDAY_0800)

    assert summary["already_done"] >= 1
    reports_after = ReportRepository(db_session).list_active_for_business(business_id, now=_MONDAY_0800)
    weekly_reports = [r for r in reports_after if r.report_type == "weekly"]
    assert len(weekly_reports) == 1  # not regenerated into a second row
    assert weekly_reports[0].updated_at == first_generated_at


def test_tick_retries_a_failed_report_under_the_attempt_cap(db_session, business_id):
    # Simulate a previous failed attempt directly (rather than forcing a
    # real failure through generate_report, which would need contriving a
    # genuine internal error) — the tick's own job is deciding whether to
    # retry it, which this exercises precisely.
    report = Report(
        business_id=business_id,
        report_type="weekly",
        period_start=datetime(2025, 12, 29, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 5, tzinfo=timezone.utc),
        status="failed",
        attempts=1,
        last_error="a transient failure",
    )
    db_session.add(report)
    db_session.commit()

    summary = run_tick(db_session, now=_MONDAY_0800)

    assert summary["permanently_failed"] == 0
    refreshed = db_session.get(Report, report.id)
    # Either recovered to completed, or failed again with attempts incremented
    # — either way, the tick must have actually tried it, not skipped it.
    assert refreshed.status in ("completed", "failed")
    if refreshed.status == "failed":
        assert refreshed.attempts == 2


def test_tick_stops_retrying_past_the_attempt_cap(db_session, business_id):
    report = Report(
        business_id=business_id,
        report_type="weekly",
        period_start=datetime(2025, 12, 29, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 5, tzinfo=timezone.utc),
        status="failed",
        attempts=MAX_ATTEMPTS,
        last_error="permanently broken",
    )
    db_session.add(report)
    db_session.commit()

    summary = run_tick(db_session, now=_MONDAY_0800)

    assert summary["permanently_failed"] >= 1
    refreshed = db_session.get(Report, report.id)
    assert refreshed.attempts == MAX_ATTEMPTS  # untouched — never retried
    assert refreshed.status == "failed"


def test_tick_writes_a_weather_snapshot_for_an_active_subscribed_business_past_the_local_hour(
    db_session, business_id, monkeypatch
):
    business = db_session.get(Business, business_id)
    business.latitude, business.longitude = Decimal("53.3806"), Decimal("-6.1750")
    db_session.add(Subscription(business_id=business_id, stripe_customer_id="cus_test_weather", status="active"))
    db_session.commit()

    forecast = [
        DailyForecast(
            day=_MONDAY_PAST_SNAPSHOT_HOUR.date(), rain_mm=Decimal("1.20"), temp_mean_c=Decimal("6.00"),
            temp_min_c=Decimal("4.00"), temp_max_c=Decimal("8.00"), wind_speed_kph=Decimal("12.00"),
        )
    ]
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: forecast)

    summary = run_tick(db_session, now=_MONDAY_PAST_SNAPSHOT_HOUR)

    assert summary["weather_snapshots_written"] >= 1
    row = WeatherObservationRepository(db_session).get(
        business_id=business_id, observed_date=_MONDAY_PAST_SNAPSHOT_HOUR.date()
    )
    assert row is not None
    assert row.rain_mm == Decimal("1.20")


def test_tick_survives_a_weather_provider_failure_without_breaking_the_rest_of_the_pass(
    db_session, business_id, monkeypatch
):
    business = db_session.get(Business, business_id)
    business.latitude, business.longitude = Decimal("53.3806"), Decimal("-6.1750")
    db_session.add(Subscription(business_id=business_id, stripe_customer_id="cus_test_weather", status="active"))
    db_session.commit()

    def _fail(**kwargs):
        raise WeatherProviderError("Met Éireann is unreachable")

    monkeypatch.setattr(weather_client, "get_forecast", _fail)

    # Must not raise, and the rest of the tick (report generation) still
    # runs normally — a weather-provider hiccup never blocks anything else.
    summary = run_tick(db_session, now=_MONDAY_PAST_SNAPSHOT_HOUR)

    assert summary["weather_snapshots_written"] == 0
    assert summary["generated"] >= 1


# --- Persistent-failure alerting ---------------------------------------------


def _failed_weekly_report(db_session, business_id, *, attempts):
    report = Report(
        business_id=business_id,
        report_type="weekly",
        period_start=datetime(2025, 12, 29, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 5, tzinfo=timezone.utc),
        status="failed",
        attempts=attempts,
        last_error="boom",
    )
    db_session.add(report)
    db_session.commit()
    return report


def _report_failed_notifications(db_session, business_id):
    rows = NotificationRepository(db_session).list_items_for_business(business_id, role="owner", category="reports")
    return [r for r in rows if r.type_key == "report_failed"]


def test_a_permanently_failed_report_raises_one_critical_alert_not_one_per_tick(db_session, business_id):
    _failed_weekly_report(db_session, business_id, attempts=MAX_ATTEMPTS)

    run_tick(db_session, now=_MONDAY_0800)
    run_tick(db_session, now=_MONDAY_0800)
    run_tick(db_session, now=_MONDAY_0800)

    alerts = _report_failed_notifications(db_session, business_id)
    assert len(alerts) == 1  # deduped by (business, report type, period)
    assert alerts[0].severity == "critical"
    assert alerts[0].action_url == "/reports"


def test_a_failure_still_under_the_retry_cap_does_not_alert(db_session, business_id):
    _failed_weekly_report(db_session, business_id, attempts=1)

    run_tick(db_session, now=_MONDAY_0800)

    assert _report_failed_notifications(db_session, business_id) == []


def test_a_permanently_failed_monthly_report_alerts_too(db_session, business_id):
    db_session.add(
        Report(
            business_id=business_id, report_type="monthly",
            period_start=datetime(2025, 12, 1, tzinfo=timezone.utc), period_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status="failed", attempts=MAX_ATTEMPTS, last_error="boom",
        )
    )
    db_session.commit()

    run_tick(db_session, now=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc))

    alerts = _report_failed_notifications(db_session, business_id)
    assert len(alerts) == 1
    assert "monthly" in alerts[0].title


# --- Daylight saving & timezone boundaries -----------------------------------
#
# Europe/Dublin 2026: clocks forward Sun 29 Mar, back Sun 25 Oct. The weekly
# report for the week ending that Sunday is due Monday 08:00 *local* — 07:00
# UTC in summer time, 08:00 UTC in winter time. January tests above can't
# catch a tick that's an hour early/late around a changeover.

_SPRING_MONDAY_0659_UTC = datetime(2026, 3, 30, 6, 59, tzinfo=timezone.utc)  # 07:59 IST — not yet due
_SPRING_MONDAY_0700_UTC = datetime(2026, 3, 30, 7, 0, tzinfo=timezone.utc)  # 08:00 IST — due
_AUTUMN_MONDAY_0700_UTC = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)  # 07:00 GMT — not yet due
_AUTUMN_MONDAY_0800_UTC = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)  # 08:00 GMT — due


def _weekly_reports(db_session, business_id):
    return [r for r in db_session.query(Report).filter(Report.business_id == business_id) if r.report_type == "weekly"]


def test_tick_waits_for_local_0800_the_morning_after_the_spring_changeover(db_session, business_id):
    run_tick(db_session, now=_SPRING_MONDAY_0659_UTC)
    assert _weekly_reports(db_session, business_id) == []

    run_tick(db_session, now=_SPRING_MONDAY_0700_UTC)
    reports = _weekly_reports(db_session, business_id)
    assert len(reports) == 1 and reports[0].status == "completed"


def test_tick_does_not_fire_an_hour_early_after_the_autumn_changeover(db_session, business_id):
    # 07:00 UTC would be 08:00 local if summer time had persisted.
    run_tick(db_session, now=_AUTUMN_MONDAY_0700_UTC)
    assert _weekly_reports(db_session, business_id) == []

    run_tick(db_session, now=_AUTUMN_MONDAY_0800_UTC)
    assert len(_weekly_reports(db_session, business_id)) == 1


def test_repeated_ticks_across_the_changeover_never_duplicate_a_report(db_session, business_id):
    for now in (_SPRING_MONDAY_0700_UTC, _SPRING_MONDAY_0700_UTC.replace(hour=8), _SPRING_MONDAY_0700_UTC.replace(day=31)):
        run_tick(db_session, now=now)

    assert len(_weekly_reports(db_session, business_id)) == 1


def test_the_changeover_week_report_covers_a_full_local_week(db_session, business_id):
    # The 23-29 Mar report is 167 real hours (clocks sprang forward inside
    # it) — it must still be the Monday-to-Sunday local week, ending at
    # local midnight Mon 30 Mar (= 23:00 UTC Sun 29 Mar).
    run_tick(db_session, now=_SPRING_MONDAY_0700_UTC)

    report = _weekly_reports(db_session, business_id)[0]
    assert report.period_start.replace(tzinfo=timezone.utc) == datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    assert report.period_end.replace(tzinfo=timezone.utc) == datetime(2026, 3, 29, 23, 0, tzinfo=timezone.utc)
    assert report.payload["period_start"].startswith("2026-03-23")
    assert report.payload["period_end"].startswith("2026-03-29")


def test_a_far_east_business_is_due_before_utc_monday_even_arrives(db_session, business_id):
    # Tokyo (UTC+9, no DST): 08:00 Monday local is 23:00 UTC *Sunday*.
    business = db_session.get(Business, business_id)
    business.timezone = "Asia/Tokyo"
    db_session.commit()

    run_tick(db_session, now=datetime(2026, 8, 2, 22, 59, tzinfo=timezone.utc))
    assert _weekly_reports(db_session, business_id) == []

    run_tick(db_session, now=datetime(2026, 8, 2, 23, 0, tzinfo=timezone.utc))
    assert len(_weekly_reports(db_session, business_id)) == 1


def test_monthly_report_follows_local_time_on_the_first_after_each_changeover_month(db_session, business_id):
    def monthly(db):
        return [r for r in db.query(Report).filter(Report.business_id == business_id) if r.report_type == "monthly"]

    run_tick(db_session, now=datetime(2026, 4, 1, 6, 59, tzinfo=timezone.utc))  # 07:59 IST
    assert monthly(db_session) == []
    run_tick(db_session, now=datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc))  # 08:00 IST
    assert len(monthly(db_session)) == 1
