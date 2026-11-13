"""On-demand "Generate report now" (found live: a new business saw an empty
Reports page until the scheduler's next tick)."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from app.models.membership import Membership
from app.models.notification import Notification
from app.models.report import Report
from app.models.sale import Sale
from tests.auth_helpers import bearer_header, patch_jwks

OWNER = bearer_header("owner-1", "owner@shop.ie")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'gen_now.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    test_client._SessionLocal = SessionLocal
    yield test_client
    app.dependency_overrides.clear()


def _business(client, headers=OWNER, name="Shop"):
    return client.post("/businesses", json={"name": name}, headers=headers).json()


def _add_sale(client, business_id, amount, days_ago=3):
    with client._SessionLocal() as db:
        db.add(
            Sale(
                business_id=uuid.UUID(business_id),
                sold_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
                total_amount=Decimal(amount),
            )
        )
        db.commit()


def test_new_business_gets_weekly_and_monthly_reports_immediately(client):
    business = _business(client)
    assert client.get(f"/businesses/{business['id']}/reports", headers=OWNER).json() == []

    response = client.post(f"/businesses/{business['id']}/reports/generate-now", headers=OWNER)
    assert response.status_code == 200
    assert sorted(r["report_type"] for r in response.json()) == ["monthly", "weekly"]
    listed = client.get(f"/businesses/{business['id']}/reports", headers=OWNER).json()
    assert len(listed) == 2

    with client._SessionLocal() as db:
        titles = {n.title for n in db.scalars(select(Notification))}
    assert {"Your weekly report is ready", "Your monthly report is ready"} <= titles


def test_generating_again_never_duplicates_and_picks_up_new_data(client):
    business = _business(client)
    client.post(f"/businesses/{business['id']}/reports/generate-now", headers=OWNER)
    with client._SessionLocal() as db:
        weekly = db.scalars(select(Report).where(Report.report_type == "weekly")).one()
        first_revenue = weekly.payload["financial_performance"]["revenue"]["current"]
        first_id = weekly.id

    # A sale inside last week's completed period, uploaded after the first report.
    today = datetime.now(timezone.utc).date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    _add_sale(client, business["id"], "125.50", days_ago=(today - last_monday).days - 2)

    client.post(f"/businesses/{business['id']}/reports/generate-now", headers=OWNER)
    with client._SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Report)) == 2  # still one per type
        weekly = db.scalars(select(Report).where(Report.report_type == "weekly")).one()
        assert weekly.id == first_id
        assert Decimal(weekly.payload["financial_performance"]["revenue"]["current"]) == Decimal(first_revenue) + Decimal("125.50")


def test_staff_cannot_generate_reports(client):
    business = _business(client)
    with client._SessionLocal() as db:
        db.add(Membership(business_id=uuid.UUID(business["id"]), user_id="staff-1", role="staff"))
        db.commit()
    staff = bearer_header("staff-1", "staff@shop.ie")
    assert client.post(f"/businesses/{business['id']}/reports/generate-now", headers=staff).status_code == 403


def test_manager_can_generate_reports(client):
    business = _business(client)
    with client._SessionLocal() as db:
        db.add(Membership(business_id=uuid.UUID(business["id"]), user_id="mgr-1", role="manager"))
        db.commit()
    manager = bearer_header("mgr-1", "mgr@shop.ie")
    assert client.post(f"/businesses/{business['id']}/reports/generate-now", headers=manager).status_code == 200


def test_cannot_generate_reports_for_another_business(client):
    business_a = _business(client, OWNER, "Shop A")
    other = bearer_header("owner-2", "owner2@shop.ie")
    _business(client, other, "Shop B")
    assert client.post(f"/businesses/{business_a['id']}/reports/generate-now", headers=other).status_code in (403, 404)
    with client._SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Report)) == 0
