import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks

_CSV_CONTENT = (
    "Order Date,Item Description,SKU,Qty,Unit Price\n"
    "2026-01-03,Chain Lube,CL-100,3,9.99\n"
    "2026-01-04,Inner Tube 700c,IT-700,10,5.50\n"
    "2026-01-05,Bar Tape,BT-200,2,12.00\n"
    "2026-01-06,Brake Pads,BP-300,4,15.25\n"
    "2026-01-07,Chain Lube,CL-100,1,9.99\n"
).encode()

_FULL_FIELD_MAPPING = {
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
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(_CSV_CONTENT))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: _CSV_CONTENT)

    db_path = tmp_path / "import_mapping_isolation_test.db"
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


def _create_business(client, headers, name):
    return client.post("/businesses", json={"name": name}, headers=headers).json()


def _upload_and_mark_uploaded(client, headers, business_id, filename):
    create_response = client.post(
        f"/businesses/{business_id}/uploads",
        json={"filename": filename, "entity_type": "sales"},
        headers=headers,
    )
    upload_id = create_response.json()["id"]
    client.post(f"/businesses/{business_id}/uploads/{upload_id}/complete", headers=headers)
    return upload_id


def test_cross_tenant_never_reuses_another_business_s_mapping_profile(client):
    """The sharpest tenant-isolation case for B7: business A and B upload
    byte-identical files (same headers). A confirms a mapping. B's
    detect-mapping must still come back needs_confirmation, never reused —
    proving the (business_id, source_signature) lookup is doing real work,
    not just that ids happen to differ.
    """
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    upload_a = _upload_and_mark_uploaded(client, headers_a, business_a["id"], "sales.csv")
    confirm_response = client.post(
        f"/businesses/{business_a['id']}/uploads/{upload_a}/confirm-mapping",
        json={"field_mapping": _FULL_FIELD_MAPPING},
        headers=headers_a,
    )
    assert confirm_response.status_code == 200

    upload_b = _upload_and_mark_uploaded(client, headers_b, business_b["id"], "sales.csv")
    detect_response = client.post(
        f"/businesses/{business_b['id']}/uploads/{upload_b}/detect-mapping", headers=headers_b
    )
    assert detect_response.status_code == 200
    assert detect_response.json()["status"] == "needs_confirmation"
    assert detect_response.json()["mapping_profile_id"] is None


def test_business_b_cannot_confirm_mapping_on_business_a_s_upload(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    upload_a = _upload_and_mark_uploaded(client, headers_a, business_a["id"], "sales.csv")

    response = client.post(
        f"/businesses/{business_b['id']}/uploads/{upload_a}/confirm-mapping",
        json={"field_mapping": _FULL_FIELD_MAPPING},
        headers=headers_b,
    )
    assert response.status_code == 404


def test_same_business_reuses_its_own_prior_mapping(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")

    upload1 = _upload_and_mark_uploaded(client, headers, business["id"], "a.csv")
    client.post(
        f"/businesses/{business['id']}/uploads/{upload1}/confirm-mapping",
        json={"field_mapping": _FULL_FIELD_MAPPING},
        headers=headers,
    )

    upload2 = _upload_and_mark_uploaded(client, headers, business["id"], "b.csv")
    detect_response = client.post(
        f"/businesses/{business['id']}/uploads/{upload2}/detect-mapping", headers=headers
    )
    assert detect_response.status_code == 200
    assert detect_response.json()["status"] == "reused"
    assert detect_response.json()["mapping_profile_id"] is not None
