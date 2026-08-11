"""HTTP-level tenant/branch-isolation tests for the global search bar
route (GET /businesses/{business_id}/search). See
tests/integration/test_search_service.py for the per-result-type
application-layer coverage (product/SKU/sale/purchase/supplier/repair
matching, PII exclusion, limits, short-query behavior).
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from app.models.membership import Membership
from app.models.product import Product
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "search_isolation_test.db"
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
    test_client = TestClient(app)
    test_client._SessionLocal = TestSessionLocal
    yield test_client
    app.dependency_overrides.clear()


def _add_staff(client, business_id, user_id="user-staff"):
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business_id), user_id=user_id, role="staff"))
    session.commit()
    session.close()


def _seed_product(client, business_id, name):
    session = client._SessionLocal()
    product = Product(business_id=uuid.UUID(business_id), name=name, sku=None, cost_price=None, sell_price=None)
    session.add(product)
    session.commit()
    session.close()


def test_search_cannot_cross_tenant(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()
    _seed_product(client, business_a["id"], "Continental GP5000 Tyre")

    # Business B's owner has no membership on A at all, so can't even attempt it.
    response = client.get(f"/businesses/{business_a['id']}/search?q=continental", headers=headers_b)
    assert response.status_code == 403


def test_non_member_gets_forbidden(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_stranger = bearer_header("user-stranger", "stranger@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    response = client.get(f"/businesses/{business['id']}/search?q=anything", headers=headers_stranger)
    assert response.status_code == 403


def test_staff_assigned_to_one_branch_cannot_search_a_sibling_branch(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    parent = client.post("/businesses", json={"name": "Main Shop"}, headers=headers_owner).json()
    branch = client.post(
        f"/businesses/{parent['id']}/branches", json={"name": "Branch Shop"}, headers=headers_owner
    ).json()
    _seed_product(client, branch["id"], "Branch-Only Widget")

    # Staff is only a member of the parent business, never the branch.
    _add_staff(client, parent["id"])
    headers_staff = bearer_header("user-staff", "staff@example.com")

    response = client.get(f"/businesses/{branch['id']}/search?q=widget", headers=headers_staff)
    assert response.status_code == 403


def test_member_can_search_their_own_business(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _seed_product(client, business["id"], "Continental GP5000 Tyre")
    _add_staff(client, business["id"])
    headers_staff = bearer_header("user-staff", "staff@example.com")

    response = client.get(f"/businesses/{business['id']}/search?q=continental", headers=headers_staff)
    assert response.status_code == 200
    body = response.json()
    assert [p["name"] for p in body["products"]] == ["Continental GP5000 Tyre"]


def test_search_result_limit_query_param_is_capped(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    response = client.get(f"/businesses/{business['id']}/search?q=widget&limit=99999", headers=headers_owner)
    # FastAPI's Query(le=MAX_LIMIT_PER_GROUP) rejects an out-of-range limit
    # outright — a caller cannot request more than the cap by asking.
    assert response.status_code == 422


def test_short_query_returns_empty_groups_not_an_error(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _seed_product(client, business["id"], "Continental GP5000 Tyre")

    response = client.get(f"/businesses/{business['id']}/search?q=c", headers=headers_owner)
    assert response.status_code == 200
    body = response.json()
    assert body == {"query": "c", "products": [], "sales": [], "purchases": [], "suppliers": [], "repairs": []}
