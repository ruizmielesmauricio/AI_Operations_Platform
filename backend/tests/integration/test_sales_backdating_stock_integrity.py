"""Calculation Test Matrix — ORLA Sales Backdating / Stock Integrity audit.

Full import-pipeline coverage (run_import/undo_import, not the repository
tests in test_date_aware_stock.py) proving the required-behaviour table
holds end to end: a sales/return/purchase row is always recorded as a
historical fact, but only ever moves *current* stock
(InventoryMovementRepository.sum_by_product_ids) when its own event date
falls after the business's latest valued stock count — regardless of what
order the underlying files were uploaded in. Each test is numbered to
match the audit prompt's own Calculation Test Matrix.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.application.products import list_product_thresholds
from app.application.retail_operations import get_retail_operations
from app.application.search import global_search
from app.imports import detection, r2_client
from app.imports.importer import run_import, undo_import
from app.models.business import Business
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.return_ import Return
from app.models.sale import Sale, SaleItem
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.upload import UploadRepository

_SALES_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price", "Order Number"]
_SALES_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
    "total_amount": None,
    "cost_price_at_sale": None,
    "order_reference": "Order Number",
}

_INVENTORY_HEADER = ["Product", "SKU", "Stock Level", "As Of Date"]
_INVENTORY_FIELD_MAPPING = {
    "product_name": "Product",
    "sku": "SKU",
    "quantity_on_hand": "Stock Level",
    "as_of_date": "As Of Date",
}

_PURCHASE_HEADER = ["Date", "Product", "SKU", "Qty Received", "Unit Cost"]
_PURCHASE_FIELD_MAPPING = {
    "purchase_date": "Date",
    "product_name": "Product",
    "sku": "SKU",
    "quantity_received": "Qty Received",
    "unit_cost": "Unit Cost",
}


@pytest.fixture()
def _fake_r2(monkeypatch):
    content_by_key: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(content_by_key[storage_key]))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: content_by_key[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)
    return content_by_key


def _make_upload(db_session, business_id, content_by_key, *, entity_type, header, content, filename, field_mapping):
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


def _sales_csv(rows: list[tuple]) -> bytes:
    lines = [",".join(_SALES_HEADER)]
    lines.extend(f"{d},{name},{sku},{qty},{price},{ref}" for d, name, sku, qty, price, ref in rows)
    return ("\n".join(lines) + "\n").encode()


def _inventory_csv(rows: list[tuple]) -> bytes:
    lines = [",".join(_INVENTORY_HEADER)]
    lines.extend(f"{name},{sku},{qty},{as_of}" for name, sku, qty, as_of in rows)
    return ("\n".join(lines) + "\n").encode()


def _purchase_csv(rows: list[tuple]) -> bytes:
    lines = [",".join(_PURCHASE_HEADER)]
    lines.extend(f"{d},{name},{sku},{qty},{cost}" for d, name, sku, qty, cost in rows)
    return ("\n".join(lines) + "\n").encode()


def _import_sales(db_session, business_id, content_by_key, rows, filename="sales.csv"):
    upload, record = _make_upload(
        db_session, business_id, content_by_key,
        entity_type="sales", header=_SALES_HEADER, content=_sales_csv(rows),
        filename=filename, field_mapping=_SALES_FIELD_MAPPING,
    )
    return run_import(db_session, upload, record), record


def _import_inventory(db_session, business_id, content_by_key, rows, filename="stock.csv"):
    upload, record = _make_upload(
        db_session, business_id, content_by_key,
        entity_type="inventory", header=_INVENTORY_HEADER, content=_inventory_csv(rows),
        filename=filename, field_mapping=_INVENTORY_FIELD_MAPPING,
    )
    return run_import(db_session, upload, record), record


def _import_purchases(db_session, business_id, content_by_key, rows, filename="purchases.csv"):
    upload, record = _make_upload(
        db_session, business_id, content_by_key,
        entity_type="purchases", header=_PURCHASE_HEADER, content=_purchase_csv(rows),
        filename=filename, field_mapping=_PURCHASE_FIELD_MAPPING,
    )
    return run_import(db_session, upload, record), record


def _stock(db_session, business_id, product_id) -> int:
    return InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product_id]).get(product_id, 0)


def _product(db_session, business_id, sku) -> Product:
    return db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == sku))


# --- 1-3: the exact scenarios named in the audit prompt -------------------


def test_1_sale_dated_before_a_later_count_is_recorded_but_not_double_subtracted(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")

    result, _ = _import_sales(
        db_session, business_id, _fake_r2, [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")]
    )
    assert result.rows_imported == 1

    sale = db_session.scalar(select(Sale).where(Sale.business_id == business_id))
    assert sale is not None
    item = db_session.scalar(select(SaleItem).where(SaleItem.sale_id == sale.id))
    assert item is not None and item.quantity == 3
    movement = db_session.scalar(
        select(InventoryMovement).where(InventoryMovement.business_id == business_id, InventoryMovement.reason == "sale")
    )
    assert movement.event_date == date(2026, 1, 9)

    assert _stock(db_session, business_id, product.id) == 40


def test_2_sale_dated_on_the_count_date_is_not_double_subtracted(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-10", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 40


def test_3_sale_dated_after_the_count_is_subtracted_exactly_once(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-11", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 37


# --- 4: mixed multi-line order ---------------------------------------------


def test_4_mixed_multi_line_order_groups_correctly_and_keeps_each_products_stock_independent(
    db_session, business_id, _fake_r2
):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    counted_product = _product(db_session, business_id, "CL-100")

    result, _ = _import_sales(
        db_session, business_id, _fake_r2,
        [
            ("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-1"),
            ("2026-01-09", "Bar Tape", "BT-200", 2, "12.00", "ORD-1"),
        ],
    )
    assert result.rows_imported == 2

    sale = db_session.scalar(select(Sale).where(Sale.business_id == business_id, Sale.order_reference == "ORD-1"))
    items = db_session.scalars(select(SaleItem).where(SaleItem.sale_id == sale.id)).all()
    assert len(items) == 2  # one grouped Sale, both lines present — not split, not duplicated

    movements = db_session.scalars(
        select(InventoryMovement).where(InventoryMovement.business_id == business_id, InventoryMovement.reason == "sale")
    ).all()
    assert {m.event_date for m in movements} == {date(2026, 1, 9)}  # every line shares the group's one date

    uncounted_product = _product(db_session, business_id, "BT-200")
    assert _stock(db_session, business_id, counted_product.id) == 40  # excluded — predates its own count
    assert _stock(db_session, business_id, uncounted_product.id) == -2  # never counted — plain signed sum


# --- 5: return symmetry -----------------------------------------------------


def test_5_return_symmetry_around_a_stock_count(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")

    _import_sales(
        db_session, business_id, _fake_r2,
        [("2026-01-08", "Chain Lube", "CL-100", -1, "9.99", "ORD-1")], filename="return-before.csv",
    )
    assert _stock(db_session, business_id, product.id) == 40  # excluded, but still recorded:
    assert db_session.scalar(select(Return).where(Return.business_id == business_id)) is not None

    _import_sales(
        db_session, business_id, _fake_r2,
        [("2026-01-11", "Chain Lube", "CL-100", -1, "9.99", "ORD-2")], filename="return-after.csv",
    )
    assert _stock(db_session, business_id, product.id) == 41  # added back exactly once


# --- 6: multiple counts ------------------------------------------------------


def test_6_sales_between_two_counts_do_not_leak_past_the_later_one(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 100, "2026-01-01")], filename="c1.csv")
    product = _product(db_session, business_id, "CL-100")
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-05", "Chain Lube", "CL-100", 30, "9.99", "ORD-1")])
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 65, "2026-01-10")], filename="c2.csv")
    assert _stock(db_session, business_id, product.id) == 65  # the Jan-10 count itself, not derived from the Jan-1 one or the sale

    _import_sales(db_session, business_id, _fake_r2, [("2026-01-15", "Chain Lube", "CL-100", 20, "9.99", "ORD-2")], filename="s2.csv")
    assert _stock(db_session, business_id, product.id) == 45  # only the post-count-2 sale affects it


# --- 7: out-of-order processing ---------------------------------------------


def test_7_out_of_order_upload_keeps_the_newest_event_date_as_baseline(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 70, "2026-01-20")], filename="current-count.csv")
    product = _product(db_session, business_id, "CL-100")
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-05", "Chain Lube", "CL-100", 5, "9.99", "ORD-1")])
    # Processed LAST (wall-clock), but dated earlier than the count already on file.
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 999, "2026-01-06")], filename="older-count.csv")

    assert _stock(db_session, business_id, product.id) == 70  # not 999 — the later-dated count still wins


# --- 8: undo ------------------------------------------------------------------


def test_8a_undoing_a_backdated_sales_import_after_a_later_count_leaves_stock_unchanged(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _, sales_record = _import_sales(db_session, business_id, _fake_r2, [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 40

    undone = undo_import(db_session, sales_record)
    assert undone.status == "reversed"
    assert db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all() == []
    assert _stock(db_session, business_id, product.id) == 40  # unchanged — it was never counted toward stock anyway


def test_8b_undoing_the_active_count_reactivates_the_prior_valid_baseline(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 100, "2026-01-01")], filename="c1.csv")
    product = _product(db_session, business_id, "CL-100")
    _, record2 = _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 65, "2026-01-10")], filename="c2.csv")
    assert _stock(db_session, business_id, product.id) == 65

    undone = undo_import(db_session, record2)
    assert undone.status == "reversed"
    assert _stock(db_session, business_id, product.id) == 100  # falls back to the still-valid Jan-1 count, never the undone one


# --- 9: no count exists ------------------------------------------------------


def test_9_no_count_exists_uses_ordinary_signed_arithmetic(db_session, business_id, _fake_r2):
    _import_sales(
        db_session, business_id, _fake_r2,
        [
            ("2026-01-03", "Chain Lube", "CL-100", 5, "9.99", "ORD-1"),
            ("2026-01-04", "Chain Lube", "CL-100", -1, "9.99", "ORD-2"),
        ],
    )
    product = _product(db_session, business_id, "CL-100")
    assert _stock(db_session, business_id, product.id) == -4  # 5 sold, 1 returned, no reconciliation baseline at all


# --- 10: purchases parity + the new sales-side warning ----------------------


def test_10_sale_and_purchase_excluded_warnings_are_present_and_consistently_worded(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")], filename="c1.csv")
    _import_inventory(db_session, business_id, _fake_r2, [("Bar Tape", "BT-200", 5, "2026-01-10")], filename="c2.csv")

    sales_result, _ = _import_sales(
        db_session, business_id, _fake_r2, [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")]
    )
    assert sales_result.rejection_summary["warnings"]["sale_excluded_from_current_stock"]["count"] == 1

    purchases_result, _ = _import_purchases(
        db_session, business_id, _fake_r2, [("2026-01-09", "Bar Tape", "BT-200", 10, "4.50")]
    )
    assert purchases_result.rejection_summary["warnings"]["purchase_excluded_from_current_stock"]["count"] == 1

    # Both facts still fully recorded, not suppressed — only the derived
    # current-stock number is unaffected.
    assert _stock(db_session, business_id, _product(db_session, business_id, "CL-100").id) == 40
    assert _stock(db_session, business_id, _product(db_session, business_id, "BT-200").id) == 5


# --- 11: tenant isolation -----------------------------------------------------


def test_11_identical_sku_reference_and_date_in_another_business_does_not_cross_contaminate(
    db_session, business_id, _fake_r2
):
    other_business = Business(name="Other Test Business")
    db_session.add(other_business)
    db_session.commit()
    other_business_id = other_business.id

    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")], filename="a.csv")
    _import_inventory(db_session, other_business_id, _fake_r2, [("Chain Lube", "CL-100", 999, "2026-01-10")], filename="b.csv")

    # Same order_reference, same SKU, same date, in the OTHER business —
    # must not collide with the first business's duplicate-reference check
    # or its stock at all.
    result, _ = _import_sales(
        db_session, other_business_id, _fake_r2,
        [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-SHARED")], filename="c.csv",
    )
    assert result.rows_imported == 1
    result2, _ = _import_sales(
        db_session, business_id, _fake_r2,
        [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-SHARED")], filename="d.csv",
    )
    assert result2.rows_imported == 1  # not rejected as a duplicate — reference dedup is per-business

    first_product = _product(db_session, business_id, "CL-100")
    other_product = _product(db_session, other_business_id, "CL-100")
    assert first_product.id != other_product.id
    assert _stock(db_session, business_id, first_product.id) == 40
    assert _stock(db_session, other_business_id, other_product.id) == 999


# --- 12: downstream regression -------------------------------------------------


def test_12_downstream_consumers_read_the_same_corrected_current_stock(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")])
    product = _product(db_session, business_id, "CL-100")

    thresholds = list_product_thresholds(db_session, business_id=business_id)
    row = next(r for r in thresholds if r.product_id == product.id)
    assert row.stock_on_hand == 40

    retail = get_retail_operations(db_session, business_id=business_id)
    cover_row = next(r for r in retail.stock_cover if r.product_id == product.id)
    assert cover_row.stock_on_hand == 40

    search_results = global_search(db_session, business_id=business_id, query="Chain Lube")
    match = next(p for p in search_results.products if p.sku == "CL-100")
    assert match.current_stock == 40

    # The sale itself is a historical fact regardless of the stock
    # exclusion — revenue reporting must still include it in full.
    sale = db_session.scalar(select(Sale).where(Sale.business_id == business_id))
    assert sale.total_amount == Decimal("29.97")  # 3 * 9.99
