import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks

_INVENTORY_FIELD_MAPPING = {
    "product_name": "Product",
    "sku": "SKU",
    "quantity_on_hand": "Stock Level",
    "unit_cost": None,
    "category": None,
    "as_of_date": None,
}
_SALES_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
    "total_amount": None,
    "cost_price_at_sale": None,
    "tax_amount": None,
    "order_reference": None,
    "category": None,
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

    db_path = tmp_path / "inventory_isolation_test.db"
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
    client._content_by_key = content_by_key  # stash for the PUT step below
    yield client
    app.dependency_overrides.clear()


def _create_business(client, headers, name):
    return client.post("/businesses", json={"name": name}, headers=headers).json()


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


def test_inventory_reconciliation_never_reads_another_business_s_stock(client):
    """The sharpest new risk this feature introduces: a bug in
    sum_by_product_ids' business scoping wouldn't just leak data, it would
    corrupt a *different tenant's* derived stock silently.
    """
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    # Both businesses stock a product under the same SKU, at very different
    # quantities — if reconciliation ever crossed tenants, one would corrupt
    # the other's derived total.
    content_a = "Product,SKU,Stock Level\nChain Lube,CL-100,25\n".encode()
    content_b = "Product,SKU,Stock Level\nChain Lube,CL-100,9999\n".encode()

    result_a = _upload_map_and_run(
        client, headers_a, business_a["id"],
        entity_type="inventory", content=content_a, filename="a.csv", field_mapping=_INVENTORY_FIELD_MAPPING,
    )
    result_b = _upload_map_and_run(
        client, headers_b, business_b["id"],
        entity_type="inventory", content=content_b, filename="b.csv", field_mapping=_INVENTORY_FIELD_MAPPING,
    )

    assert result_a["rows_imported"] == 1
    assert result_b["rows_imported"] == 1

    # Re-run each business's own reconciliation with an unchanged count —
    # if sum_by_product_ids ever looked across tenants, business A's second
    # pass would see business B's 9999 bleed in and compute a nonsense delta.
    result_a2 = _upload_map_and_run(
        client, headers_a, business_a["id"],
        entity_type="inventory", content=content_a, filename="a2.csv", field_mapping=_INVENTORY_FIELD_MAPPING,
    )
    assert result_a2["rows_imported"] == 1
    assert result_a2["rejection_summary"] is None  # no warnings — a clean zero-delta no-op


