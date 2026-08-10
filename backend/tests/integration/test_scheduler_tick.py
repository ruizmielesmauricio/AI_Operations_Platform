"""Stage D17/D18 — verifies app/scheduler/tick.py's reconciliation logic
(which of PR-8.1/8.2's scheduling, PR-8.9's retry, and PR-8.10's recovery
actually fire) against a real (SQLite) database.
"""

from datetime import datetime, timezone

from app.models.report import Report
from app.repositories.report import MAX_ATTEMPTS, ReportRepository
from app.scheduler.tick import run_tick

# A Monday, 08:00 exactly — the weekly generation moment for the previous
# completed week. January in Dublin (the default business timezone) is
# GMT, no DST offset to account for.
_MONDAY_0800 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


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
