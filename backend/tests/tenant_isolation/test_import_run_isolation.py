import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks, seed_active_subscription

_CSV_CONTENT = (
    "Order Date,Item Description,SKU,Qty,Unit Price\n"
    "2026-01-03,Chain Lube,CL-100,3,9.99\n"
    "2026-01-04,Bar Tape,BT-200,1,12.00\n"
).encode()

_FIELD_MAPPING = {
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
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)

    db_path = tmp_path / "import_run_isolation_test.db"
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
    test_client._engine = engine  # stashed so _create_business can seed an active subscription
    yield test_client
    app.dependency_overrides.clear()


def _create_business(client, headers, name):
    # Uploads/imports now require an active subscription
    # (app/billing/access.py::require_active_subscription) — seeded here,
    # bypassing Stripe entirely, since these tests are about tenant
    # isolation, not billing state.
    business = client.post("/businesses", json={"name": name}, headers=headers).json()
    seed_active_subscription(client._engine, business["id"])
    return business


def _upload_and_confirm(client, headers, business_id, filename):
    create_response = client.post(
        f"/businesses/{business_id}/uploads",
        json={"filename": filename, "entity_type": "sales"},
        headers=headers,
    )
    upload_id = create_response.json()["id"]
    client.post(f"/businesses/{business_id}/uploads/{upload_id}/complete", headers=headers)
    confirm_response = client.post(
        f"/businesses/{business_id}/uploads/{upload_id}/confirm-mapping",
        json={"field_mapping": _FIELD_MAPPING},
        headers=headers,
    )
    assert confirm_response.status_code == 200
    return upload_id


def test_running_import_creates_sales_and_returns_a_summary(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")
    upload_id = _upload_and_confirm(client, headers, business["id"], "sales.csv")

    response = client.post(f"/businesses/{business['id']}/uploads/{upload_id}/import", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["rows_imported"] == 2
    assert body["rows_rejected"] == 0


def test_upload_list_exposes_the_import_record_summary(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")
    upload_id = _upload_and_confirm(client, headers, business["id"], "sales.csv")

    # Before running: confirm-mapping already created the ImportRecord
    # (status "mapped"), it just hasn't processed any rows yet.
    before = client.get(f"/businesses/{business['id']}/uploads", headers=headers).json()
    row = next(u for u in before if u["id"] == upload_id)
    assert row["status"] == "mapped"
    assert row["import_record"]["status"] == "mapped"
    assert row["import_record"]["rows_total"] == 0

    client.post(f"/businesses/{business['id']}/uploads/{upload_id}/import", headers=headers)

    after = client.get(f"/businesses/{business['id']}/uploads", headers=headers).json()
    row = next(u for u in after if u["id"] == upload_id)
    assert row["status"] == "imported"
    assert row["import_record"]["status"] == "completed"
    assert row["import_record"]["rows_imported"] == 2


def test_cannot_run_import_on_another_business_s_upload(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    upload_id = _upload_and_confirm(client, headers_a, business_a["id"], "sales.csv")

    response = client.post(f"/businesses/{business_b['id']}/uploads/{upload_id}/import", headers=headers_b)
    assert response.status_code == 404


def test_cannot_undo_another_business_s_import(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    upload_id = _upload_and_confirm(client, headers_a, business_a["id"], "sales.csv")
    import_response = client.post(
        f"/businesses/{business_a['id']}/uploads/{upload_id}/import", headers=headers_a
    )
    import_record_id = import_response.json()["import_record_id"]

    response = client.post(
        f"/businesses/{business_b['id']}/import-records/{import_record_id}/undo", headers=headers_b
    )
    assert response.status_code == 404


def test_running_import_is_blocked_once_the_subscription_is_no_longer_active(client):
    # Confirms run_import has its own require_active_subscription gate,
    # independent of the one on request_upload — subscribed through the
    # whole upload/confirm-mapping flow, then the subscription lapses
    # (a direct DB write, mirroring what a real Stripe cancellation
    # webhook would do) before the actual import runs.
    import uuid

    from sqlalchemy.orm import sessionmaker

    from app.models.subscription import Subscription

    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")
    upload_id = _upload_and_confirm(client, headers, business["id"], "sales.csv")

    session = sessionmaker(bind=client._engine, autoflush=False, expire_on_commit=False)()
    subscription = session.query(Subscription).filter_by(business_id=uuid.UUID(business["id"])).one()
    subscription.status = "canceled"
    session.commit()
    session.close()

    response = client.post(f"/businesses/{business['id']}/uploads/{upload_id}/import", headers=headers)
    assert response.status_code == 402


def test_undo_via_api_reverses_the_import_and_rejects_a_second_undo(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")
    upload_id = _upload_and_confirm(client, headers, business["id"], "sales.csv")
    import_response = client.post(
        f"/businesses/{business['id']}/uploads/{upload_id}/import", headers=headers
    )
    import_record_id = import_response.json()["import_record_id"]

    undo_response = client.post(
        f"/businesses/{business['id']}/import-records/{import_record_id}/undo", headers=headers
    )
    assert undo_response.status_code == 200
    assert undo_response.json()["status"] == "reversed"

    second_undo = client.post(
        f"/businesses/{business['id']}/import-records/{import_record_id}/undo", headers=headers
    )
    assert second_undo.status_code == 409
