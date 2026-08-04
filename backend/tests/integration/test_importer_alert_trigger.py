"""Stage C12 — verifies the actual hook wiring in app/imports/importer.py
(not just app/application/alerts.py in isolation): a real run_import call
that pushes a product's stock into low-stock territory creates a
persisted Alert, and undoing that same import resolves it again.
"""

import pytest
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.importer import run_import, undo_import
from app.models.alert import Alert
from app.models.product import Product
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository

_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price"]
# A brand-new product (never purchased into stock before) sold here goes
# straight to negative derived stock -> compute_stock_cover_days treats
# that as "out of stock now" (cover_days=0), which is always <= any
# threshold — deterministically triggers low_stock without needing to
# tune exact sales-velocity numbers.
_CSV_CONTENT = "Order Date,Item Description,SKU,Qty,Unit Price\n2026-01-03,Chain Lube,CL-100,5,9.99\n".encode()

_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
    "total_amount": None,
    "cost_price_at_sale": None,
    "order_reference": None,
}


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(_CSV_CONTENT))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: _CSV_CONTENT)
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)


def _make_mapped_upload(db_session, business_id):
    upload = UploadRepository(db_session).create(
        business_id=business_id,
        storage_key=f"{business_id}/test/sales.csv",
        original_filename="sales.csv",
        uploaded_by="user-a",
        entity_type="sales",
    )
    upload = UploadRepository(db_session).set_status(upload, status="uploaded")

    signature = detection.compute_source_signature("sales", _HEADER)
    profile = ImportMappingProfileRepository(db_session).upsert(
        business_id=business_id,
        source_signature=signature,
        column_mapping={"entity_type": "sales", "engine_version": 1, "fields": _FIELD_MAPPING},
    )
    record = ImportRecordRepository(db_session).create(
        business_id=business_id,
        upload_id=upload.id,
        mapping_profile_id=profile.id,
        entity_type="sales",
        status="mapped",
    )
    upload = UploadRepository(db_session).set_status(upload, status="mapped")
    return upload, record


def test_run_import_creates_a_low_stock_alert_and_undo_resolves_it(db_session, business_id):
    upload, record = _make_mapped_upload(db_session, business_id)

    run_import(db_session, upload, record)

    product = db_session.scalars(select(Product).where(Product.business_id == business_id, Product.sku == "CL-100")).one()
    alerts = db_session.scalars(
        select(Alert).where(
            Alert.business_id == business_id, Alert.product_id == product.id, Alert.status == "active"
        )
    ).all()
    assert len(alerts) == 1
    assert alerts[0].alert_type == "low_stock"
    assert alerts[0].payload["severity"] == "critical"  # negative derived stock -> out of stock now

    undo_import(db_session, record)

    active_alerts = db_session.scalars(
        select(Alert).where(Alert.business_id == business_id, Alert.status == "active")
    ).all()
    assert active_alerts == []

    resolved_alerts = db_session.scalars(
        select(Alert).where(Alert.business_id == business_id, Alert.status == "resolved")
    ).all()
    assert len(resolved_alerts) == 1
    assert resolved_alerts[0].id == alerts[0].id  # same row, not a new one
