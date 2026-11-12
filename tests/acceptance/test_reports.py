"""Scheduled reports, weekly Monday / monthly 1st — AC-033..AC-042 (criteria §5)."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from conftest import SALES_HEADER, auth, csv_bytes, recent_weekly_run, utc


def _tick(orla, now):
    from app.scheduler.tick import run_tick

    with orla.session() as s:
        return run_tick(s, now=now)


def _reports(orla, biz_id, report_type=None):
    from app.models.report import Report

    with orla.session() as s:
        q = s.query(Report).filter(Report.business_id == uuid.UUID(biz_id))
        if report_type:
            q = q.filter(Report.report_type == report_type)
        return q.all()


def _local_date(dt, tz):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz)).date().isoformat()


@pytest.mark.parametrize("tz,due_utc", [
    ("Europe/Dublin", utc(2026, 3, 30, 7, 0)),       # IST (UTC+1), first Monday after the clocks change
    ("America/New_York", utc(2026, 3, 30, 12, 0)),   # EDT (UTC-4)
])
def test_weekly_due_monday_0800_local(orla, tz, due_utc):
    """AC-033: weekly report becomes due Monday 08:00 local, covers the
    previous Monday-Sunday, never earlier."""
    biz = orla.create_business(f"wk-{tz}", timezone_name=tz)
    _tick(orla, due_utc - timedelta(minutes=1))
    assert not [r for r in _reports(orla, biz["id"], "weekly") if _local_date(r.period_start, tz) == "2026-03-23"], \
        "weekly report generated before Monday 08:00 local"
    _tick(orla, due_utc)
    weekly = [r for r in _reports(orla, biz["id"], "weekly") if _local_date(r.period_start, tz) == "2026-03-23"]
    assert len(weekly) == 1 and weekly[0].status == "completed"
    assert weekly[0].payload["period_start"] == "2026-03-23"
    assert weekly[0].payload["period_end"] == "2026-03-29"


def test_monthly_due_first_0800_local(orla):
    """AC-034: monthly report due on the 1st at 08:00 local, previous month."""
    biz = orla.create_business("mo-user")
    due = utc(2026, 4, 1, 7, 0)  # 08:00 IST
    _tick(orla, due - timedelta(minutes=1))
    assert not [r for r in _reports(orla, biz["id"], "monthly")
                if _local_date(r.period_start, "Europe/Dublin") == "2026-03-01"]
    _tick(orla, due)
    monthly = [r for r in _reports(orla, biz["id"], "monthly")
               if _local_date(r.period_start, "Europe/Dublin") == "2026-03-01"]
    assert len(monthly) == 1 and monthly[0].status == "completed"
    assert (monthly[0].payload["period_start"], monthly[0].payload["period_end"]) == ("2026-03-01", "2026-03-31")


def test_coinciding_schedules_two_reports(orla):
    """AC-035: Monday the 1st -> separate weekly and monthly reports, each with
    its own notification."""
    from app.models.notification import Notification

    biz = orla.create_business("both-user")
    _tick(orla, utc(2026, 6, 1, 7, 0))  # Monday 1 June 2026, 08:00 IST
    weekly = [r for r in _reports(orla, biz["id"], "weekly") if r.payload and r.payload["period_end"] == "2026-05-31"]
    monthly = [r for r in _reports(orla, biz["id"], "monthly") if r.payload and r.payload["period_end"] == "2026-05-31"]
    assert len(weekly) == 1 and len(monthly) == 1
    with orla.session() as s:
        ready = s.query(Notification).filter(
            Notification.business_id == uuid.UUID(biz["id"]), Notification.type_key == "report_ready"
        ).all()
    assert {n.related_entity_id for n in ready} >= {weekly[0].id, monthly[0].id}


def test_generation_idempotent(orla):
    """AC-036: repeated ticks never duplicate; the database itself enforces it."""
    from sqlalchemy.exc import IntegrityError

    from app.models.report import Report

    biz = orla.create_business("idem-rep")
    for _ in range(3):
        _tick(orla, utc(2026, 1, 5, 9, 0))
    weekly = _reports(orla, biz["id"], "weekly")
    assert len(weekly) == 1
    with orla.session() as s:
        s.add(Report(business_id=uuid.UUID(biz["id"]), report_type="weekly",
                     period_start=weekly[0].period_start, period_end=weekly[0].period_end, status="pending"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_in_app_only_no_email_no_file(orla):
    """AC-037: generating reports sends no email and writes no file."""
    biz = orla.create_business("inapp-user")
    orla.import_file("inapp-user", biz["id"], "s.csv", csv_bytes([
        SALES_HEADER, ["2026-05-26", "Widget", "W", "2", "5.00", "2.00"],
    ]))
    puts_before = len(orla.r2.puts)
    _tick(orla, utc(2026, 6, 1, 7, 0))
    assert any(r.status == "completed" for r in _reports(orla, biz["id"]))
    assert orla.email.sent == []
    assert len(orla.r2.puts) == puts_before


def _recent_report(orla, user="recent-user"):
    run_at, week = recent_weekly_run()
    biz = orla.create_business(user)
    orla.import_file(user, biz["id"], "s.csv", csv_bytes([
        SALES_HEADER, [week[1].isoformat(), "Widget", "W", "2", "5.00", "2.00"],
    ]))
    _tick(orla, run_at)
    weekly = next(r for r in _reports(orla, biz["id"], "weekly") if r.status == "completed" and r.expires_at)
    weekly.run_at = run_at
    return biz, weekly


def test_seven_day_expiry_and_audit_record(orla):
    """AC-038: available 7 days; the notification states the exact expiry
    date; after expiry the content is gone but the operational record stays."""
    from app.models.notification import Notification
    from app.models.report import Report

    biz, report = _recent_report(orla)
    expires = report.expires_at if report.expires_at.tzinfo else report.expires_at.replace(tzinfo=timezone.utc)
    assert expires - report.run_at == timedelta(days=7), "report must stay available exactly seven days"

    with orla.session() as s:
        note = s.query(Notification).filter(
            Notification.related_entity_id == report.id, Notification.type_key == "report_ready").one()
    local = expires.astimezone(ZoneInfo("Europe/Dublin")).date()
    formats = {local.isoformat(), local.strftime("%d/%m/%Y"), f"{local.day} {local.strftime('%B %Y')}",
               f"{local.day} {local.strftime('%b %Y')}"}
    assert any(f in note.body or f in note.title for f in formats), f"expiry date not shown: {note.body!r}"

    ok = orla.client.get(f"/businesses/{biz['id']}/reports/{report.id}", headers=auth("recent-user"))
    assert ok.status_code == 200
    with orla.session() as s:
        row = s.get(Report, report.id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    gone = orla.client.get(f"/businesses/{biz['id']}/reports/{report.id}", headers=auth("recent-user"))
    assert gone.status_code in (404, 410)
    with orla.session() as s:
        row = s.get(Report, report.id)
        assert row is not None and row.status and row.attempts is not None
        assert row.created_at and row.updated_at
        assert s.query(Notification).filter(Notification.related_entity_id == report.id).count() >= 1


def test_on_demand_exports(orla):
    """AC-039: PDF and Word only on request, real files, members only."""
    biz, report = _recent_report(orla, "export-user")
    h = auth("export-user")
    pdf = orla.client.get(f"/businesses/{biz['id']}/reports/{report.id}/download.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert "pdf" in pdf.headers.get("content-type", "")
    docx = orla.client.get(f"/businesses/{biz['id']}/reports/{report.id}/download.docx", headers=h)
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    outsider = orla.client.get(f"/businesses/{biz['id']}/reports/{report.id}/download.pdf", headers=auth("stranger"))
    assert outsider.status_code in (403, 404)


def test_bounded_retry_and_operator_alert(orla, monkeypatch):
    """AC-040: transient failures retry a bounded number of times; persistent
    failure creates an operator alert. Contract: an audit_logs row with
    action "report_generation_failed", target_type "report", and metadata
    containing report_type, period_start, attempts, last_error."""
    from app.application import report as report_app
    from app.models.audit_log import AuditLog

    biz = orla.create_business("fail-user")

    def broken(*args, **kwargs):
        raise RuntimeError("injected persistent failure")

    monkeypatch.setattr(report_app, "_assemble_payload", broken)
    start = utc(2026, 1, 5, 8, 0)
    for i in range(15):
        _tick(orla, start + timedelta(hours=i))
    weekly = _reports(orla, biz["id"], "weekly")
    assert len(weekly) == 1 and weekly[0].status == "failed"
    assert 2 <= weekly[0].attempts <= 10, f"retry policy unbounded or absent: {weekly[0].attempts} attempts"
    with orla.session() as s:
        alerts = s.query(AuditLog).filter(AuditLog.business_id == uuid.UUID(biz["id"]),
                                          AuditLog.action == "report_generation_failed").all()
    assert alerts, "no operator alert recorded after persistent failure"
    meta = alerts[-1].event_metadata or {}
    assert meta.get("report_type") == "weekly"
    assert str(meta.get("period_start", "")).startswith("2025-12-29")
    assert int(meta.get("attempts")) == weekly[0].attempts
    assert "injected persistent failure" in str(meta.get("last_error"))


def test_missed_report_recovered(orla):
    """AC-041: if the Monday run never happened, the next pass catches up."""
    biz = orla.create_business("missed-user")
    _tick(orla, utc(2026, 1, 6, 10, 0))  # Tuesday — the Monday 08:00 run was missed
    weekly = [r for r in _reports(orla, biz["id"], "weekly") if r.payload and r.payload["period_start"] == "2025-12-29"]
    assert len(weekly) == 1 and weekly[0].status == "completed"


def test_report_content_matches_fixture(orla):
    """AC-042: every PR-8.3 section is present and its figures match an
    independent hand calculation.

    Contract (payload keys): top_selling_products / bottom_selling_products
    (3 each, ranked by units sold); profit_and_expenses {revenue, expenses,
    profit} where expenses = cost of goods sold for the period; plus the
    existing financial_performance (with previous-period comparison),
    executive_summary.narrative, forecast, findings.recommendations,
    executive_summary.low_stock_count, data_freshness and warnings."""
    run_at, week = recent_weekly_run()
    prior = [d - timedelta(days=7) for d in week]
    biz = orla.create_business("content-user")
    rows = [SALES_HEADER,
            [week[0].isoformat(), "Alpha", "A", "10", "5.00", "2.00"],
            [week[1].isoformat(), "Bravo", "B", "8", "10.00", "4.00"],
            [week[2].isoformat(), "Charlie", "C", "6", "3.00", "1.00"],
            [week[3].isoformat(), "Delta", "D", "2", "20.00", "15.00"],
            [week[4].isoformat(), "Echo", "E", "1", "7.00", "3.00"],
            [prior[0].isoformat(), "Alpha", "A", "5", "5.00", "2.00"],
            [prior[1].isoformat(), "Bravo", "B", "5", "10.00", "4.00"]]
    orla.import_file("content-user", biz["id"], "s.csv", csv_bytes(rows))
    _tick(orla, run_at)
    report = next(r for r in _reports(orla, biz["id"], "weekly") if r.status == "completed")
    p = report.payload

    fin = p["financial_performance"]
    assert Decimal(fin["revenue"]["current"]) == Decimal("195.00")
    assert Decimal(fin["revenue"]["previous"]) == Decimal("75.00")
    assert Decimal(fin["revenue"]["change_pct"]) == Decimal("160.00")
    assert Decimal(fin["gross_margin"]["gross_profit"]) == Decimal("104.00")

    pe = p["profit_and_expenses"]
    assert (Decimal(pe["revenue"]), Decimal(pe["expenses"]), Decimal(pe["profit"])) == (
        Decimal("195.00"), Decimal("91.00"), Decimal("104.00"))
    assert [x["name"] for x in p["top_selling_products"]] == ["Alpha", "Bravo", "Charlie"]
    assert [x["name"] for x in p["bottom_selling_products"]] == ["Echo", "Delta", "Charlie"]

    assert isinstance(p["executive_summary"]["narrative"], str) and p["executive_summary"]["narrative"].strip()
    assert "forecast" in p and "recommendations" in p["findings"]
    assert "low_stock_count" in p["executive_summary"]
    assert p["data_freshness"].get("sales"), "data freshness for sales missing"
    assert isinstance(p["warnings"], list) and p["warnings"], "missing-data warnings absent (no stock data uploaded)"
