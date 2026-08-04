import pytest
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.exceptions import ImportNotReversible
from app.imports.importer import run_import, undo_import
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository

_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price"]
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
    "order_reference": None,
}


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(_CSV_CONTENT))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: _CSV_CONTENT)
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)


def _make_mapped_upload(db_session, business_id, filename="sales.csv"):
    upload = UploadRepository(db_session).create(
        business_id=business_id,
        storage_key=f"{business_id}/test/{filename}",
        original_filename=filename,
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


def test_undo_removes_everything_the_import_created(db_session, business_id):
    upload, record = _make_mapped_upload(db_session, business_id)
    run_import(db_session, upload, record)
    assert db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()

    undone = undo_import(db_session, record)

    assert undone.status == "reversed"
    assert undone.reversed_at is not None
    assert db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all() == []
    assert db_session.scalars(select(SaleItem)).all() == []
    assert db_session.scalars(select(InventoryMovement)).all() == []

    # The upload event genuinely happened and the file's already gone from
    # R2 — undo doesn't revert Upload.status back to "mapped".
    refreshed_upload = UploadRepository(db_session).get_for_business(upload.id, business_id)
    assert refreshed_upload.status == "imported"


def test_undo_leaves_auto_created_products_in_place(db_session, business_id):
    upload, record = _make_mapped_upload(db_session, business_id)
    run_import(db_session, upload, record)
    products_before = db_session.scalars(select(Product).where(Product.business_id == business_id)).all()
    assert products_before

    undo_import(db_session, record)

    products_after = db_session.scalars(select(Product).where(Product.business_id == business_id)).all()
    assert len(products_after) == len(products_before)


def test_undo_only_affects_its_own_import(db_session, business_id):
    upload1, record1 = _make_mapped_upload(db_session, business_id, filename="a.csv")
    run_import(db_session, upload1, record1)
    upload2, record2 = _make_mapped_upload(db_session, business_id, filename="b.csv")
    run_import(db_session, upload2, record2)

    undo_import(db_session, record1)

    assert db_session.scalars(select(Sale).where(Sale.import_record_id == record1.id)).all() == []
    assert db_session.scalars(select(Sale).where(Sale.import_record_id == record2.id)).all()  # untouched


def test_undo_rejects_an_import_that_never_completed(db_session, business_id):
    upload, record = _make_mapped_upload(db_session, business_id)  # never run
    with pytest.raises(ImportNotReversible):
        undo_import(db_session, record)


def test_undo_rejects_an_already_reversed_import(db_session, business_id):
    upload, record = _make_mapped_upload(db_session, business_id)
    run_import(db_session, upload, record)
    undo_import(db_session, record)
    with pytest.raises(ImportNotReversible):
        undo_import(db_session, record)
