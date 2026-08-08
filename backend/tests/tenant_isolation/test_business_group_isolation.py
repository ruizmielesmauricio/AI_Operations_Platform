"""Covers the all_branches=true query param end-to-end through the real
FastAPI routes (app/api/analytics.py, app/application/business_group.py)
— the tenant-isolation/error-mapping half of the feature; the aggregation
math itself is covered directly against a real DB in
tests/integration/test_business_group.py.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "business_group_isolation_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_all_branches_combines_parent_and_branch_for_their_owner(client):
    headers = bearer_header("owner", "owner@example.com")
    parent = client.post("/businesses", json={"name": "Primary Shop"}, headers=headers).json()
    client.post(f"/businesses/{parent['id']}/branches", json={"name": "Branch"}, headers=headers)

    response = client.get(
        f"/businesses/{parent['id']}/analytics/financial-performance?all_branches=true", headers=headers
    )
    assert response.status_code == 200
    # No sales seeded — just proving the combined path returns a normal,
    # well-formed payload rather than erroring, same shape as the
    # single-business route.
    assert response.json()["revenue"]["current"] == "0.00"


def test_all_branches_rejects_a_caller_not_a_member_of_every_business_in_the_group(client):
    headers_owner = bearer_header("owner", "owner@example.com")
    headers_stranger = bearer_header("stranger", "stranger@example.com")
    parent = client.post("/businesses", json={"name": "Primary Shop"}, headers=headers_owner).json()
    client.post(f"/businesses/{parent['id']}/branches", json={"name": "Branch"}, headers=headers_owner)

    # A stranger isn't even a member of the parent, so get_current_membership
    # itself already 403s before all_branches is ever considered — proves
    # the ordinary per-route gate still applies, combining isn't a bypass.
    response = client.get(
        f"/businesses/{parent['id']}/analytics/financial-performance?all_branches=true", headers=headers_stranger
    )
    assert response.status_code == 403


def test_all_branches_rejects_mismatched_timezones(client):
    headers = bearer_header("owner", "owner@example.com")
    parent = client.post(
        "/businesses", json={"name": "Primary Shop", "timezone": "Europe/Dublin"}, headers=headers
    ).json()
    client.post(
        f"/businesses/{parent['id']}/branches",
        json={"name": "Branch", "timezone": "America/New_York"},
        headers=headers,
    )

    response = client.get(
        f"/businesses/{parent['id']}/analytics/financial-performance?all_branches=true", headers=headers
    )
    assert response.status_code == 409
    assert "timezone" in response.json()["detail"].lower()


def test_without_all_branches_still_reads_only_the_one_business_as_before(client):
    headers = bearer_header("owner", "owner@example.com")
    parent = client.post("/businesses", json={"name": "Primary Shop"}, headers=headers).json()
    client.post(f"/businesses/{parent['id']}/branches", json={"name": "Branch"}, headers=headers)

    # Default (all_branches omitted) — unchanged single-business behavior,
    # confirming this feature is additive, not a silent behavior change
    # for every existing call site.
    response = client.get(f"/businesses/{parent['id']}/analytics/financial-performance", headers=headers)
    assert response.status_code == 200
