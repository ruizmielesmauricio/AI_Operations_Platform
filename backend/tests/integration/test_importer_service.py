import pytest
from decimal import Decimal
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.exceptions import ImportRecordNotReady, MappedColumnMissing
from app.imports.importer import run_import
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository

_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price", "Order Number"]
_CSV_CONTENT = (
    "Order Date,Item Description,SKU,Qty,Unit Price,Order Number\n"
    "2026-01-03,Chain Lube,CL-100,3,9.99,ORD-1\n"
    "2026-01-03,Bar Tape,BT-200,1,12.00,ORD-1\n"
    "2026-01-04,Inner Tube 700c,IT-700,10,5.50,ORD-2\n"
    "2026-01-05,Whatever,CL-100,2,9.99,ORD-3\n"
).replace("2026-01-05", "not-a-date", 1).encode()  # last row deliberately has an unparseable date

_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
    "total_amount": None,
    "cost_price_at_sale": None,
    "order_reference": "Order Number",
}


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(_CSV_CONTENT))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: _CSV_CONTENT)
    deleted: list[str] = []
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: deleted.append(storage_key))
    return deleted


def _make_mapped_upload(db_session, business_id, filename="sales.csv", field_mapping=None):
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
        column_mapping={
            "entity_type": "sales",
            "engine_version": 1,
            "fields": field_mapping or _FIELD_MAPPING,
        },
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


def test_run_import_creates_sales_sale_items_and_inventory_movements(db_session, business_id, _fake_r2):
    upload, record = _make_mapped_upload(db_session, business_id)

    result = run_import(db_session, upload, record)

    assert result.status == "completed"
    assert result.rows_total == 4
    assert result.rows_imported == 3
    assert result.rows_rejected == 1
    assert result.rejection_summary["reasons"]["missing_date"]["count"] == 1

    sales = db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()
    assert len(sales) == 2  # ORD-1 (2 items) + ORD-2 (1 item); the rejected row's ORD-3 never happened
    ord1 = next(s for s in sales if s.order_reference == "ORD-1")
    assert ord1.total_amount == Decimal("41.97")  # 3*9.99 + 1*12.00
    assert ord1.import_record_id == record.id

    items = db_session.scalars(select(SaleItem)).all()
    assert len(items) == 3

    products = db_session.scalars(select(Product).where(Product.business_id == business_id)).all()
    assert {p.sku for p in products} == {"CL-100", "BT-200", "IT-700"}

    movements = db_session.scalars(select(InventoryMovement)).all()
    assert len(movements) == 3
    assert all(m.reason == "sale" for m in movements)
    cl100 = next(p for p in products if p.sku == "CL-100")
    cl100_movement = next(m for m in movements if m.product_id == cl100.id)
    assert cl100_movement.quantity_delta == -3

    refreshed_upload = UploadRepository(db_session).get_for_business(upload.id, business_id)
    assert refreshed_upload.status == "imported"

    assert _fake_r2 == [upload.storage_key]  # deleted only after success


def test_run_import_matches_an_existing_product_by_sku_on_a_second_import(db_session, business_id, _fake_r2):
    upload1, record1 = _make_mapped_upload(db_session, business_id, filename="a.csv")
    run_import(db_session, upload1, record1)

    upload2, record2 = _make_mapped_upload(db_session, business_id, filename="b.csv")
    run_import(db_session, upload2, record2)

    products = db_session.scalars(
        select(Product).where(Product.business_id == business_id, Product.sku == "CL-100")
    ).all()
    assert len(products) == 1  # not duplicated across two imports

    sale_items = db_session.scalars(select(SaleItem).where(SaleItem.product_id == products[0].id)).all()
    assert len(sale_items) == 2  # one line from each import, same product


def test_run_import_requires_the_mapped_state(db_session, business_id):
    upload, record = _make_mapped_upload(db_session, business_id)
    upload = UploadRepository(db_session).set_status(upload, status="uploaded")  # regress state
    with pytest.raises(ImportRecordNotReady):
        run_import(db_session, upload, record)


def test_run_import_raises_when_a_mapped_column_is_no_longer_in_the_file(db_session, business_id):
    bad_mapping = dict(_FIELD_MAPPING, sale_date="Not A Real Column")
    upload, record = _make_mapped_upload(db_session, business_id, field_mapping=bad_mapping)
    with pytest.raises(MappedColumnMissing):
        run_import(db_session, upload, record)
