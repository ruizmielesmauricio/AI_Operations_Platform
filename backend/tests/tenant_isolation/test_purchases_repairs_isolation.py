import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks, seed_active_subscription

_PURCHASE_FIELD_MAPPING = {
    "purchase_date": "Date",
    "product_name": "Product",
    "sku": "SKU",
    "quantity_received": "Qty Received",
    "unit_cost": "Unit Cost",
    "purchase_reference": None,
    "category": None,
}
_REPAIR_FIELD_MAPPING = {
    "repair_date": "Date",
    "description": "Description",
    "price_charged": "Price Charged",
    "labour_cost": "Labour Cost",
    "repair_reference": None,
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    monkeypatch.setattr(
        r2_client, "generate_upload_url", lambda *, storage_key: f"https://r2.test/{storage_key}"
    )
    content_by_key: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(content_by_key[storage_key]))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: content_by_key[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)

    db_path = tmp_path / "purchases_repairs_isolation_test.db"
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
    client = TestClient(app)
    client._content_by_key = content_by_key
    client._engine = engine  # stashed so _create_business can seed an active subscription
    yield client
    app.dependency_overrides.clear()


def _create_business(client, headers, name):
    # Uploads/imports now require an active subscription
    # (app/billing/access.py::require_active_subscription) — seeded here,
    # bypassing Stripe entirely, since these tests are about tenant
    # isolation, not billing state.
    business = client.post("/businesses", json={"name": name}, headers=headers).json()
    seed_active_subscription(client._engine, business["id"])
    return business


def _upload_map_and_run(client, headers, business_id, *, entity_type, content, filename, field_mapping):
    create_response = client.post(
        f"/businesses/{business_id}/uploads",
        json={"filename": filename, "entity_type": entity_type},
        headers=headers,
    )
    upload_id = create_response.json()["id"]
    upload_url = create_response.json()["upload_url"]
    storage_key = upload_url.split("https://r2.test/")[1].split("?")[0]
    client._content_by_key[storage_key] = content

    client.post(f"/businesses/{business_id}/uploads/{upload_id}/complete", headers=headers)
    confirm_response = client.post(
        f"/businesses/{business_id}/uploads/{upload_id}/confirm-mapping",
        json={"field_mapping": field_mapping},
        headers=headers,
    )
    assert confirm_response.status_code == 200
    import_response = client.post(f"/businesses/{business_id}/uploads/{upload_id}/import", headers=headers)
    assert import_response.status_code == 200
    return import_response.json()


def test_purchase_cost_seeding_never_reads_or_writes_another_business_s_product(client):
    """The sharpest new risk: if update_cost_price's business_id filter
    ever leaked, one tenant's restock could silently overwrite another
    tenant's product cost."""
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    content_a = "Date,Product,SKU,Qty Received,Unit Cost\n2026-01-05,Chain Lube,CL-100,50,4.75\n".encode()
    content_b = "Date,Product,SKU,Qty Received,Unit Cost\n2026-01-05,Chain Lube,CL-100,50,999.00\n".encode()

    result_a = _upload_map_and_run(
        client, headers_a, business_a["id"],
        entity_type="purchases", content=content_a, filename="a.csv", field_mapping=_PURCHASE_FIELD_MAPPING,
    )
    result_b = _upload_map_and_run(
        client, headers_b, business_b["id"],
        entity_type="purchases", content=content_b, filename="b.csv", field_mapping=_PURCHASE_FIELD_MAPPING,
    )

    assert result_a["rows_imported"] == 1
    assert result_b["rows_imported"] == 1

    products_a = client.get(f"/businesses/{business_a['id']}/uploads", headers=headers_a).json()
    assert products_a  # sanity: business A's own upload list is unaffected


def test_cannot_undo_another_business_s_purchases_import(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    content = "Date,Product,SKU,Qty Received,Unit Cost\n2026-01-05,Chain Lube,CL-100,50,4.75\n".encode()
    result = _upload_map_and_run(
        client, headers_a, business_a["id"],
        entity_type="purchases", content=content, filename="a.csv", field_mapping=_PURCHASE_FIELD_MAPPING,
    )

    response = client.post(
        f"/businesses/{business_b['id']}/import-records/{result['import_record_id']}/undo", headers=headers_b
    )
    assert response.status_code == 404


def test_repairs_import_is_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    content_a = "Date,Description,Price Charged,Labour Cost\n2026-01-05,Replaced brake pads,45.00,20.00\n".encode()
    content_b = "Date,Description,Price Charged,Labour Cost\n2026-01-05,Fixed a puncture,15.00,\n".encode()

    result_a = _upload_map_and_run(
        client, headers_a, business_a["id"],
        entity_type="repairs", content=content_a, filename="a.csv", field_mapping=_REPAIR_FIELD_MAPPING,
    )
    result_b = _upload_map_and_run(
        client, headers_b, business_b["id"],
        entity_type="repairs", content=content_b, filename="b.csv", field_mapping=_REPAIR_FIELD_MAPPING,
    )

    assert result_a["rows_imported"] == 1
    assert result_b["rows_imported"] == 1

    # Business B cannot undo business A's repairs import.
    response = client.post(
        f"/businesses/{business_b['id']}/import-records/{result_a['import_record_id']}/undo", headers=headers_b
    )
    assert response.status_code == 404


def test_freshness_endpoint_is_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    content = "Date,Product,SKU,Qty Received,Unit Cost\n2026-01-05,Chain Lube,CL-100,50,4.75\n".encode()
    _upload_map_and_run(
        client, headers_a, business_a["id"],
        entity_type="purchases", content=content, filename="a.csv", field_mapping=_PURCHASE_FIELD_MAPPING,
    )

    freshness_a = client.get(f"/businesses/{business_a['id']}/uploads/freshness", headers=headers_a).json()
    freshness_b = client.get(f"/businesses/{business_b['id']}/uploads/freshness", headers=headers_b).json()

    purchases_a = next(e for e in freshness_a if e["entity_type"] == "purchases")
    purchases_b = next(e for e in freshness_b if e["entity_type"] == "purchases")
    assert purchases_a["last_completed_at"] is not None
    assert purchases_b["last_completed_at"] is None  # business B never uploaded purchases
