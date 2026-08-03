import pytest
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.exceptions import ImportSupersededByLaterInventoryImport
from app.imports.importer import run_import, undo_import
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository

_INVENTORY_HEADER = ["Product", "SKU", "Stock Level"]
_INVENTORY_CSV = (
    "Product,SKU,Stock Level\n"
    "Chain Lube,CL-100,25\n"
    "Bar Tape,BT-200,8\n"
).encode()
_INVENTORY_FIELD_MAPPING = {"product_name": "Product", "sku": "SKU", "quantity_on_hand": "Stock Level"}

_SALES_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price"]
_SALES_CSV = (
    "Order Date,Item Description,SKU,Qty,Unit Price\n"
    "2026-01-03,Chain Lube,CL-100,3,9.99\n"
).encode()
_SALES_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
    "total_amount": None,
    "cost_price_at_sale": None,
    "order_reference": None,
}


@pytest.fixture()
def _fake_r2(monkeypatch):
    content_by_key: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(content_by_key[storage_key]))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: content_by_key[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)
    return content_by_key


def _make_mapped_upload(db_session, business_id, content_by_key, *, entity_type, header, content, filename):
    storage_key = f"{business_id}/test/{filename}"
    content_by_key[storage_key] = content

    upload = UploadRepository(db_session).create(
        business_id=business_id,
        storage_key=storage_key,
        original_filename=filename,
        uploaded_by="user-a",
        entity_type=entity_type,
    )
    upload = UploadRepository(db_session).set_status(upload, status="uploaded")

    signature = detection.compute_source_signature(entity_type, header)
    field_mapping = _INVENTORY_FIELD_MAPPING if entity_type == "inventory" else _SALES_FIELD_MAPPING
    profile = ImportMappingProfileRepository(db_session).upsert(
        business_id=business_id,
        source_signature=signature,
        column_mapping={"entity_type": entity_type, "engine_version": 1, "fields": field_mapping},
    )
    record = ImportRecordRepository(db_session).create(
        business_id=business_id,
        upload_id=upload.id,
        mapping_profile_id=profile.id,
        entity_type=entity_type,
        status="mapped",
    )
    upload = UploadRepository(db_session).set_status(upload, status="mapped")
    return upload, record


def _make_inventory_upload(db_session, business_id, content_by_key, filename="stock.csv", content=_INVENTORY_CSV):
    return _make_mapped_upload(
        db_session, business_id, content_by_key,
        entity_type="inventory", header=_INVENTORY_HEADER, content=content, filename=filename,
    )


def _make_sales_upload(db_session, business_id, content_by_key, filename="sales.csv", content=_SALES_CSV):
    return _make_mapped_upload(
        db_session, business_id, content_by_key,
        entity_type="sales", header=_SALES_HEADER, content=content, filename=filename,
    )


def test_inventory_import_creates_only_adjustment_movements(db_session, business_id, _fake_r2):
    upload, record = _make_inventory_upload(db_session, business_id, _fake_r2)

    result = run_import(db_session, upload, record)

    assert result.status == "completed"
    assert result.rows_imported == 2
    assert result.rows_rejected == 0

    assert db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all() == []

    movements = db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all()
    assert len(movements) == 2
    assert all(m.reason == "adjustment" for m in movements)
    assert all(m.import_record_id == record.id for m in movements)
    assert all(m.reference_id is None for m in movements)

    products = db_session.scalars(select(Product).where(Product.business_id == business_id)).all()
    assert {p.sku for p in products} == {"CL-100", "BT-200"}
    # New products created by an inventory import start with no price data.
    assert all(p.cost_price is None and p.sell_price is None for p in products)


def test_second_inventory_import_reconciles_against_the_first(db_session, business_id, _fake_r2):
    upload1, record1 = _make_inventory_upload(db_session, business_id, _fake_r2, filename="a.csv")
    run_import(db_session, upload1, record1)

    second_content = (
        "Product,SKU,Stock Level\n"
        "Chain Lube,CL-100,30\n"  # was 25, now 30 -> delta +5
        "Bar Tape,BT-200,8\n"  # unchanged -> delta 0, no movement
    ).encode()
    upload2, record2 = _make_inventory_upload(
        db_session, business_id, _fake_r2, filename="b.csv", content=second_content
    )
    result = run_import(db_session, upload2, record2)

    assert result.rows_imported == 2

    cl100 = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "CL-100"))
    movements = db_session.scalars(
        select(InventoryMovement).where(
            InventoryMovement.business_id == business_id, InventoryMovement.product_id == cl100.id
        )
    ).all()
    # First import: +25 (new product). Second import: +5 (30-25). No
    # movement at all for Bar Tape's second (zero-delta) row.
    assert sorted(m.quantity_delta for m in movements) == [5, 25]
    assert sum(m.quantity_delta for m in movements) == 30


def test_duplicate_product_within_one_inventory_file_compounds_and_warns(db_session, business_id, _fake_r2):
    content = (
        "Product,SKU,Stock Level\n"
        "Chain Lube,CL-100,15\n"
        "Chain Lube,CL-100,15\n"
    ).encode()
    upload, record = _make_inventory_upload(db_session, business_id, _fake_r2, content=content)

    result = run_import(db_session, upload, record)

    assert result.rows_imported == 2
    assert result.rejection_summary["warnings"]["duplicate_product_in_file"]["count"] == 1

    product = db_session.scalar(select(Product).where(Product.business_id == business_id))
    movements = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.product_id == product.id)
    ).all()
    assert sum(m.quantity_delta for m in movements) == 15  # not 30


def test_undo_inventory_import_bulk_deletes_by_import_record_id(db_session, business_id, _fake_r2):
    upload, record = _make_inventory_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload, record)
    assert db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all()

    undone = undo_import(db_session, record)

    assert undone.status == "reversed"
    assert db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all() == []
    # Products auto-created by this import are deliberately left in place.
    assert db_session.scalars(select(Product).where(Product.business_id == business_id)).all()


def test_undoing_a_sales_import_is_blocked_by_a_later_inventory_reconciliation(db_session, business_id, _fake_r2):
    """The exact bug scenario the design review found: stock=0 -> sales
    import writes -3 -> inventory reconciliation reads current stock (-3),
    targets 25, writes +28 -> undoing the *sales* import (if allowed) would
    leave stock at 0+28=28, silently wrong. Must be blocked instead.
    """
    sales_content = (
        "Order Date,Item Description,SKU,Qty,Unit Price\n"
        "2026-01-03,Chain Lube,CL-100,3,9.99\n"
    ).encode()
    upload1, sales_record = _make_sales_upload(db_session, business_id, _fake_r2, content=sales_content)
    run_import(db_session, upload1, sales_record)

    inventory_content = "Product,SKU,Stock Level\nChain Lube,CL-100,25\n".encode()
    upload2, inventory_record = _make_inventory_upload(
        db_session, business_id, _fake_r2, filename="stock.csv", content=inventory_content
    )
    run_import(db_session, upload2, inventory_record)

    product = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "CL-100"))
    stock_before = sum(
        m.quantity_delta
        for m in db_session.scalars(
            select(InventoryMovement).where(InventoryMovement.product_id == product.id)
        ).all()
    )
    assert stock_before == 25  # reconciliation succeeded: -3 + 28 = 25

    with pytest.raises(ImportSupersededByLaterInventoryImport):
        undo_import(db_session, sales_record)

    # Confirm nothing was touched by the failed undo attempt.
    stock_after = sum(
        m.quantity_delta
        for m in db_session.scalars(
            select(InventoryMovement).where(InventoryMovement.product_id == product.id)
        ).all()
    )
    assert stock_after == 25
    assert db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()


def test_undoing_the_most_recent_inventory_import_is_still_allowed(db_session, business_id, _fake_r2):
    upload, record = _make_inventory_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload, record)

    undone = undo_import(db_session, record)  # no later inventory import exists
    assert undone.status == "reversed"
