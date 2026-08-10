import pytest
from decimal import Decimal
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.exceptions import ImportRecordNotReady, MappedColumnMissing
from app.imports.importer import run_import, undo_import
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.return_ import Return
from app.models.sale import Sale, SaleItem
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.inventory_movement import InventoryMovementRepository
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

# A second file's content, reusing CL-100 (to exercise cross-import SKU
# matching) but with its own order references — a real second sale, not a
# re-upload of the first file, so it must NOT collide with the
# duplicate_reference dedup check (app/imports/importer.py::_write_sales).
_CSV_CONTENT_B = (
    "Order Date,Item Description,SKU,Qty,Unit Price,Order Number\n"
    "2026-01-06,Chain Lube,CL-100,1,9.99,ORD-4\n"
).encode()


class _DeletedKeys(list):
    """A plain list of deleted storage keys, plus a bag for per-test
    per-storage-key content overrides (see _CSV_CONTENT_B above) — a
    subclass rather than a bare list purely so tests can stash
    content_by_key on the fixture's return value."""

    content_by_key: dict[str, bytes]


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    content_by_key: dict[str, bytes] = {}

    def _download(*, storage_key):
        return content_by_key.get(storage_key, _CSV_CONTENT)

    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(_download(storage_key=storage_key)))
    monkeypatch.setattr(r2_client, "download_object", _download)
    deleted = _DeletedKeys()
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: deleted.append(storage_key))
    deleted.content_by_key = content_by_key
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


_CSV_CONTENT_RETURNS = (
    "Order Date,Item Description,SKU,Qty,Unit Price,Order Number\n"
    "2026-01-03,Chain Lube,CL-100,5,9.99,ORD-10\n"
    "2026-01-04,Chain Lube,CL-100,-1,9.99,ORD-11\n"
).encode()


def test_run_import_accepts_a_return_and_restores_stock_and_nets_revenue(db_session, business_id, _fake_r2):
    # Real bug found via Gate B testing with synthetic_sales.csv: a
    # negative-quantity row (a return, mixed into the same sales file)
    # used to be rejected outright as non_positive_quantity, silently
    # excluding real refund data from every calculation.
    upload, record = _make_mapped_upload(db_session, business_id, filename="returns.csv")
    _fake_r2.content_by_key[upload.storage_key] = _CSV_CONTENT_RETURNS

    result = run_import(db_session, upload, record)

    assert result.status == "completed"
    assert result.rows_total == 2
    assert result.rows_imported == 2  # the return is accepted, not rejected
    assert result.rows_rejected == 0
    assert "reasons" not in (result.rejection_summary or {})
    assert result.rejection_summary["warnings"]["sales_includes_returns"]["count"] == 1

    sales = db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()
    assert len(sales) == 2
    return_sale = next(s for s in sales if s.order_reference == "ORD-11")
    # unit_price (9.99, positive, from the file) * quantity (-1) — the
    # refunded amount, correctly negative.
    assert return_sale.total_amount == Decimal("-9.99")

    returns = db_session.scalars(select(Return).where(Return.business_id == business_id)).all()
    assert len(returns) == 1
    assert returns[0].refund_amount == Decimal("9.99")
    assert returns[0].reason is None  # the file gives no reason data — never invented

    movements = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.business_id == business_id)
    ).all()
    assert len(movements) == 2
    sale_movement = next(m for m in movements if m.reason == "sale")
    return_movement = next(m for m in movements if m.reason == "return")
    assert sale_movement.quantity_delta == -5
    assert return_movement.quantity_delta == 1  # stock restored, not further decreased

    product = db_session.scalars(select(Product).where(Product.business_id == business_id)).one()
    stock = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock[product.id] == -4  # 5 sold, 1 returned — net stock impact


def test_run_import_matches_an_existing_product_by_sku_on_a_second_import(db_session, business_id, _fake_r2):
    upload1, record1 = _make_mapped_upload(db_session, business_id, filename="a.csv")
    run_import(db_session, upload1, record1)

    upload2, record2 = _make_mapped_upload(db_session, business_id, filename="b.csv")
    _fake_r2.content_by_key[upload2.storage_key] = _CSV_CONTENT_B
    run_import(db_session, upload2, record2)

    products = db_session.scalars(
        select(Product).where(Product.business_id == business_id, Product.sku == "CL-100")
    ).all()
    assert len(products) == 1  # not duplicated across two imports

    sale_items = db_session.scalars(select(SaleItem).where(SaleItem.product_id == products[0].id)).all()
    assert len(sale_items) == 2  # one line from each import, same product


def test_reuploading_a_file_with_an_already_used_order_reference_rejects_the_whole_group(db_session, business_id, _fake_r2):
    # ORD-1 is a two-row group (Chain Lube + Bar Tape). Re-uploading a
    # second file that reuses ORD-1 must reject BOTH of its rows, not just
    # the first — a multi-line sale sharing one order_reference is one
    # economic event.
    upload1, record1 = _make_mapped_upload(db_session, business_id, filename="a.csv")
    run_import(db_session, upload1, record1)
    sales_after_first = db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()
    assert len(sales_after_first) == 2  # ORD-1 + ORD-2 (ORD-3's row is rejected for missing_date)

    upload2, record2 = _make_mapped_upload(db_session, business_id, filename="b.csv")
    result = run_import(db_session, upload2, record2)

    assert result.rows_imported == 0
    assert result.rows_rejected == 4  # ORD-1 (2 rows) + ORD-2 (1 row) + the unparseable-date row
    assert result.rejection_summary["reasons"]["duplicate_reference"]["count"] == 3

    sales_after_second = db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()
    assert len(sales_after_second) == 2  # nothing new written — no double-counted revenue


def test_undo_then_reupload_with_the_same_order_reference_succeeds(db_session, business_id, _fake_r2):
    upload1, record1 = _make_mapped_upload(db_session, business_id, filename="a.csv")
    run_import(db_session, upload1, record1)

    undone = undo_import(db_session, record1)
    assert undone.status == "reversed"
    assert db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all() == []

    upload2, record2 = _make_mapped_upload(db_session, business_id, filename="b.csv")
    result = run_import(db_session, upload2, record2)

    assert result.rows_imported == 3  # succeeds exactly as the first import did
    sales = db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()
    assert {s.order_reference for s in sales} == {"ORD-1", "ORD-2"}


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
