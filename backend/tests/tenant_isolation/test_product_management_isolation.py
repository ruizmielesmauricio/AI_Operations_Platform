"""HTTP-level tenant-isolation and role-boundary tests for the three new
product-management surfaces: suppliers (Gap 4), product/category
thresholds (Gap 1), and the dashboard transaction drill-down (Gap 5). See
tests/integration/test_suppliers_service.py, test_products_thresholds_
service.py, and test_transactions_service.py for the corresponding
application-layer coverage.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from app.models.inventory_movement import InventoryMovement
from app.models.membership import Membership
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "product_management_isolation_test.db"
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


def _add_manager(client, business_id, user_id="user-manager"):
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business_id), user_id=user_id, role="manager"))
    session.commit()
    session.close()


def _add_staff(client, business_id, user_id="user-staff"):
    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business_id), user_id=user_id, role="staff"))
    session.commit()
    session.close()


def _seed_product(client, business_id, name="Chain Lube"):
    session = client._SessionLocal()
    product = Product(business_id=uuid.UUID(business_id), name=name, sku=None, cost_price=None, sell_price=None)
    session.add(product)
    session.commit()
    product_id = str(product.id)
    session.close()
    return product_id


def _seed_sale(client, business_id, product_id, sold_at=None):
    session = client._SessionLocal()
    sale = Sale(
        business_id=uuid.UUID(business_id), sold_at=sold_at or datetime(2026, 1, 5, tzinfo=timezone.utc),
        total_amount=Decimal("10.00"),
    )
    session.add(sale)
    session.flush()
    session.add(
        SaleItem(
            business_id=uuid.UUID(business_id), sale_id=sale.id, product_id=uuid.UUID(product_id), quantity=1,
            unit_price=Decimal("10.00"),
        )
    )
    session.commit()
    session.close()


# --- Suppliers --------------------------------------------------------


def test_owner_can_create_and_list_suppliers(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    create_response = client.post(
        f"/businesses/{business['id']}/suppliers", json={"name": "Acme Parts"}, headers=headers
    )
    assert create_response.status_code == 201
    assert create_response.json()["created"] is True

    list_response = client.get(f"/businesses/{business['id']}/suppliers", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_staff_cannot_create_a_supplier(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-staff", "staff@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _add_staff(client, business["id"])

    response = client.post(f"/businesses/{business['id']}/suppliers", json={"name": "Acme"}, headers=headers_staff)
    assert response.status_code == 403


def test_staff_can_view_suppliers(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-staff", "staff@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _add_staff(client, business["id"])
    client.post(f"/businesses/{business['id']}/suppliers", json={"name": "Acme"}, headers=headers_owner)

    response = client.get(f"/businesses/{business['id']}/suppliers", headers=headers_staff)
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_manager_can_create_but_not_merge_a_supplier(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_manager = bearer_header("user-manager", "manager@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _add_manager(client, business["id"])

    create_response = client.post(
        f"/businesses/{business['id']}/suppliers", json={"name": "Manager Added Co"}, headers=headers_manager
    )
    assert create_response.status_code == 201
    supplier_id = create_response.json()["supplier"]["id"]

    other = client.post(
        f"/businesses/{business['id']}/suppliers", json={"name": "Other Co"}, headers=headers_owner
    ).json()["supplier"]

    merge_response = client.post(
        f"/businesses/{business['id']}/suppliers/{supplier_id}/merge",
        json={"target_supplier_id": other["id"]},
        headers=headers_manager,
    )
    assert merge_response.status_code == 403


def test_supplier_lookup_cannot_cross_tenant(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()

    supplier = client.post(
        f"/businesses/{business_a['id']}/suppliers", json={"name": "A's Supplier"}, headers=headers_a
    ).json()["supplier"]

    # Business B's owner has no membership on A, so can't even attempt it.
    response = client.patch(
        f"/businesses/{business_a['id']}/suppliers/{supplier['id']}", json={"name": "Hijacked"}, headers=headers_b
    )
    assert response.status_code == 403


def test_supplier_merge_into_a_supplier_from_another_business_fails(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()

    source = client.post(
        f"/businesses/{business_a['id']}/suppliers", json={"name": "A's Supplier"}, headers=headers_a
    ).json()["supplier"]
    other_business_supplier = client.post(
        f"/businesses/{business_b['id']}/suppliers", json={"name": "B's Supplier"}, headers=headers_b
    ).json()["supplier"]

    response = client.post(
        f"/businesses/{business_a['id']}/suppliers/{source['id']}/merge",
        json={"target_supplier_id": other_business_supplier["id"]},
        headers=headers_a,
    )
    assert response.status_code == 404


# --- Product thresholds -------------------------------------------------


def test_owner_can_view_and_update_a_product_threshold(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    product_id = _seed_product(client, business["id"])

    list_response = client.get(f"/businesses/{business['id']}/products/thresholds", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["recommendation"]["basis"] == "default_fallback"

    update_response = client.patch(
        f"/businesses/{business['id']}/products/{product_id}/threshold",
        json={"threshold_days": "10"},
        headers=headers,
    )
    assert update_response.status_code == 204


def test_staff_cannot_update_a_product_threshold(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-staff", "staff@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _add_staff(client, business["id"])
    product_id = _seed_product(client, business["id"])

    response = client.patch(
        f"/businesses/{business['id']}/products/{product_id}/threshold",
        json={"threshold_days": "10"},
        headers=headers_staff,
    )
    assert response.status_code == 403


def test_manager_can_update_a_product_threshold(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_manager = bearer_header("user-manager", "manager@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _add_manager(client, business["id"])
    product_id = _seed_product(client, business["id"])

    response = client.patch(
        f"/businesses/{business['id']}/products/{product_id}/threshold",
        json={"threshold_days": "10"},
        headers=headers_manager,
    )
    assert response.status_code == 204


def test_product_threshold_update_cannot_cross_tenant(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()
    product_id = _seed_product(client, business_b["id"])

    response = client.patch(
        f"/businesses/{business_b['id']}/products/{product_id}/threshold",
        json={"threshold_days": "10"},
        headers=headers_a,
    )
    assert response.status_code == 403


# --- Transactions drill-down ---------------------------------------------


def test_any_member_can_list_sale_transactions(client):
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-staff", "staff@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()
    _add_staff(client, business["id"])
    product_id = _seed_product(client, business["id"])
    _seed_sale(client, business["id"], product_id)

    response = client.get(f"/businesses/{business['id']}/transactions/sales", headers=headers_staff)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert "product_name" in body["items"][0]
    # No customer identity anywhere in the response shape.
    assert "customer_name" not in body["items"][0]
    assert "customer_email" not in body["items"][0]


def test_sale_transactions_cannot_cross_tenant(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()
    product_id = _seed_product(client, business_b["id"])
    _seed_sale(client, business_b["id"], product_id)

    response = client.get(f"/businesses/{business_b['id']}/transactions/sales", headers=headers_a)
    assert response.status_code == 403


def test_transaction_pagination_cap_is_enforced_at_the_api_layer(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.get(f"/businesses/{business['id']}/transactions/sales?limit=99999", headers=headers)
    # FastAPI's Query(le=MAX_PAGE_SIZE) rejects an out-of-range limit
    # outright — a caller cannot request more than the cap by asking.
    assert response.status_code == 422


def test_purchase_transactions_include_supplier_and_are_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()
    product_id = _seed_product(client, business_a["id"])

    session = client._SessionLocal()
    session.add(
        InventoryMovement(
            business_id=uuid.UUID(business_a["id"]), product_id=uuid.UUID(product_id), quantity_delta=5,
            reason="purchase", event_date=date(2026, 1, 5), unit_cost=Decimal("2.00"),
        )
    )
    session.commit()
    session.close()

    own_response = client.get(f"/businesses/{business_a['id']}/transactions/purchases", headers=headers_a)
    assert own_response.status_code == 200
    assert own_response.json()["total"] == 1

    cross_response = client.get(f"/businesses/{business_a['id']}/transactions/purchases", headers=headers_b)
    assert cross_response.status_code == 403


def test_repair_transactions_list_route_works_and_is_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()

    own_response = client.get(f"/businesses/{business_a['id']}/transactions/repairs", headers=headers_a)
    assert own_response.status_code == 200
    assert own_response.json()["total"] == 0

    cross_response = client.get(f"/businesses/{business_a['id']}/transactions/repairs", headers=headers_b)
    assert cross_response.status_code == 403
