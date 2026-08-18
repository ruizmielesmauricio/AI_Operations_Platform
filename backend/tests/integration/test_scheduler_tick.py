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
