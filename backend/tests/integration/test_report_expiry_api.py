"""The report seven-day expiry countdown through the real API — for BOTH
weekly and monthly reports (same expiry rule, ADR-019), on both the list
and the detail route."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.application.report import generate_report
from app.main import app
from app.models import Base
from app.models.report import Report
from tests.auth_helpers import bearer_header, patch_jwks

_SEVEN_DAYS = 7 * 24 * 3600


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'report_expiry_test.db'}")
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


def _business_with_both_report_types(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    db = client._SessionLocal()
    now = datetime.now(timezone.utc)
    ids = {
        report_type: generate_report(db, business_id=uuid.UUID(business["id"]), report_type=report_type, now=now).id
        for report_type in ("weekly", "monthly")
    }
    db.close()
    return headers, business["id"], ids


@pytest.mark.parametrize("report_type", ["weekly", "monthly"])
def test_list_shows_a_full_seven_day_countdown_for_a_fresh_report(client, report_type):
    headers, business_id, ids = _business_with_both_report_types(client)

    rows = client.get(f"/businesses/{business_id}/reports", headers=headers).json()

    row = next(r for r in rows if r["report_type"] == report_type)
    assert _SEVEN_DAYS - 120 <= row["seconds_until_expiry"] <= _SEVEN_DAYS
    assert row["expiring_soon"] is False


@pytest.mark.parametrize("report_type", ["weekly", "monthly"])
def test_detail_shows_the_same_countdown(client, report_type):
    headers, business_id, ids = _business_with_both_report_types(client)

    body = client.get(f"/businesses/{business_id}/reports/{ids[report_type]}", headers=headers).json()

    assert _SEVEN_DAYS - 120 <= body["seconds_until_expiry"] <= _SEVEN_DAYS
    assert body["expiring_soon"] is False


@pytest.mark.parametrize("report_type", ["weekly", "monthly"])
def test_a_report_with_a_day_left_is_flagged_expiring_soon(client, report_type):
    headers, business_id, ids = _business_with_both_report_types(client)
    db = client._SessionLocal()
    report = db.get(Report, ids[report_type])
    report.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    db.commit()
    db.close()

    body = client.get(f"/businesses/{business_id}/reports/{ids[report_type]}", headers=headers).json()
    listed = next(
        r for r in client.get(f"/businesses/{business_id}/reports", headers=headers).json() if r["id"] == str(ids[report_type])
    )

    for payload in (body, listed):
        assert 24 * 3600 - 120 <= payload["seconds_until_expiry"] <= 24 * 3600
        assert payload["expiring_soon"] is True


def test_the_two_report_types_count_down_independently(client):
    headers, business_id, ids = _business_with_both_report_types(client)
    db = client._SessionLocal()
    db.get(Report, ids["weekly"]).expires_at = datetime.now(timezone.utc) + timedelta(hours=3)
    db.commit()
    db.close()

    rows = {r["report_type"]: r for r in client.get(f"/businesses/{business_id}/reports", headers=headers).json()}

    assert rows["weekly"]["expiring_soon"] is True
    assert rows["monthly"]["expiring_soon"] is False


def test_an_expired_report_still_reads_as_not_found_not_a_zero_countdown(client):
    # Unchanged behaviour: an expired report is hidden entirely (404), the
    # countdown never has to represent "already gone".
    headers, business_id, ids = _business_with_both_report_types(client)
    db = client._SessionLocal()
    db.get(Report, ids["monthly"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()

    assert client.get(f"/businesses/{business_id}/reports/{ids['monthly']}", headers=headers).status_code == 404
    assert all(r["report_type"] != "monthly" for r in client.get(f"/businesses/{business_id}/reports", headers=headers).json())
