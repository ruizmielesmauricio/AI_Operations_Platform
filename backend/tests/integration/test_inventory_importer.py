from decimal import Decimal

import pytest
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.importer import run_import, undo_import
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.upload import UploadRepository

_INVENTORY_HEADER = ["Product", "SKU", "Stock Level"]
_INVENTORY_CSV = (
    "Product,SKU,Stock Level\n"
    "Chain Lube,CL-100,25\n"
    "Bar Tape,BT-200,8\n"
).encode()
_INVENTORY_FIELD_MAPPING = {"product_name": "Product", "sku": "SKU", "quantity_on_hand": "Stock Level"}

_INVENTORY_WITH_COST_HEADER = ["Product", "SKU", "Stock Level", "Unit Cost"]
_INVENTORY_WITH_COST_FIELD_MAPPING = {
    "product_name": "Product",
    "sku": "SKU",
    "quantity_on_hand": "Stock Level",
    "unit_cost": "Unit Cost",
}

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


def _make_mapped_upload(
    db_session, business_id, content_by_key, *, entity_type, header, content, filename, field_mapping=None
):
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
    if field_mapping is None:
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


def _make_inventory_upload_with_cost(db_session, business_id, content_by_key, *, content, filename="stock.csv"):
    return _make_mapped_upload(
        db_session, business_id, content_by_key,
        entity_type="inventory", header=_INVENTORY_WITH_COST_HEADER, content=content, filename=filename,
        field_mapping=_INVENTORY_WITH_COST_FIELD_MAPPING,
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


def test_inventory_import_with_unit_cost_seeds_and_updates_product_cost_price(db_session, business_id, _fake_r2):
    # Chain Lube is new (cost seeded at creation); Bar Tape already exists
    # from a prior sales import with a different cost (cost updated via
    # ProductRepository.update_cost_price, the same path purchases uses).
    first_upload, first_record = _make_sales_upload(
        db_session, business_id, _fake_r2, filename="sales.csv",
        content=(
            "Order Date,Item Description,SKU,Qty,Unit Price\n"
            "2026-01-03,Bar Tape,BT-200,1,15.00\n"
        ).encode(),
    )
    run_import(db_session, first_upload, first_record)
    bar_tape = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "BT-200"))
    assert bar_tape.cost_price is None  # no cost_price_at_sale was mapped in that file either

    content = (
        "Product,SKU,Stock Level,Unit Cost\n"
        "Chain Lube,CL-100,25,3.00\n"
        "Bar Tape,BT-200,8,4.50\n"
    ).encode()
    upload, record = _make_inventory_upload_with_cost(db_session, business_id, _fake_r2, content=content)

    result = run_import(db_session, upload, record)
    assert result.rows_imported == 2

    chain_lube = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "CL-100"))
    assert chain_lube.cost_price == Decimal("3.00")

    db_session.refresh(bar_tape)
    assert bar_tape.cost_price == Decimal("4.50")

    # Stock adjustment still happens exactly as without a cost column — the
    # +9 (not +8) for Bar Tape is correct: it reconciles against -1, its
    # stock after the prior sale, not against a bare "8" the file claims.
    adjustments = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.business_id == business_id, InventoryMovement.reason == "adjustment")
    ).all()
    assert sorted(m.quantity_delta for m in adjustments) == [9, 25]


def test_inventory_import_cost_only_row_updates_cost_without_a_stock_movement(db_session, business_id, _fake_r2):
    upload1, record1 = _make_inventory_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload1, record1)

    content = (
        "Product,SKU,Stock Level,Unit Cost\n"
        "Chain Lube,CL-100,25,5.25\n"  # same 25 -> delta 0, cost-only change
    ).encode()
    upload2, record2 = _make_inventory_upload_with_cost(
        db_session, business_id, _fake_r2, content=content, filename="stock2.csv"
    )
    run_import(db_session, upload2, record2)

    chain_lube = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "CL-100"))
    assert chain_lube.cost_price == Decimal("5.25")

    # Two movements now, not one — a zero-delta reconciliation is still
    # written (unlike before this test was updated) so its as_of_date
    # becomes the new baseline for future stock reads; a "confirmed still
    # 25 units" event is real information, even with no quantity change.
    movements = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.business_id == business_id, InventoryMovement.product_id == chain_lube.id)
    ).all()
    assert sorted(m.quantity_delta for m in movements) == [0, 25]
    zero_delta_movement = next(m for m in movements if m.quantity_delta == 0)
    assert zero_delta_movement.resulting_quantity_on_hand == 25


def test_duplicate_product_in_file_uses_the_last_unit_cost(db_session, business_id, _fake_r2):
    content = (
        "Product,SKU,Stock Level,Unit Cost\n"
        "Chain Lube,CL-100,15,3.00\n"
        "Chain Lube,CL-100,15,3.50\n"
    ).encode()
    upload, record = _make_inventory_upload_with_cost(db_session, business_id, _fake_r2, content=content)

    result = run_import(db_session, upload, record)
    assert result.rejection_summary["warnings"]["duplicate_product_in_file"]["count"] == 1

    product = db_session.scalar(select(Product).where(Product.business_id == business_id))
    assert product.cost_price == Decimal("3.50")  # last row wins, same as quantity


def test_undo_inventory_import_bulk_deletes_by_import_record_id(db_session, business_id, _fake_r2):
    upload, record = _make_inventory_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload, record)
    assert db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all()

    undone = undo_import(db_session, record)

    assert undone.status == "reversed"
    assert db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all() == []
    # Products auto-created by this import are deliberately left in place.
    assert db_session.scalars(select(Product).where(Product.business_id == business_id)).all()


def test_undoing_a_sales_import_before_a_later_reconciliation_now_succeeds_correctly(db_session, business_id, _fake_r2):
    """The exact bug scenario the design review originally found, now
    replayed under the date-aware calculation
    (InventoryMovementRepository.sum_by_product_ids): a sale dated
    2026-01-03, then a stock-count reconciliation (dated "today", since no
    as_of_date column is mapped) targeting 25. Undoing the sale used to be
    *blocked* outright (v1.19's ImportSupersededByLaterInventoryImport) to
    prevent a stale +delta from silently corrupting the total. Now it's
    unconditionally safe: the reconciliation stores its own absolute
    resulting_quantity_on_hand (25) rather than a delta computed against a
    mutable running sum, and the sale (dated well before the
    reconciliation) was never counted toward "current stock" in the first
    place — so deleting it changes nothing about the calculated total.
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
    stock_before = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock_before[product.id] == 25  # the reconciliation's own number, not a derived sum

    undone = undo_import(db_session, sales_record)
    assert undone.status == "reversed"

    stock_after = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock_after[product.id] == 25  # unchanged — not 28, not any other silently-wrong number

    # The sale itself really is gone (undo succeeded, not a no-op).
    assert db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all() == []


def test_undoing_the_most_recent_inventory_import_is_still_allowed(db_session, business_id, _fake_r2):
    upload, record = _make_inventory_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload, record)

    undone = undo_import(db_session, record)  # no later inventory import exists
    assert undone.status == "reversed"
