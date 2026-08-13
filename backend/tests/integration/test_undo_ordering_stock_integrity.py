"""Undo-Ordering / Date-Aware Stock Regression Audit.

Proves `app/imports/importer.py::undo_import` remains safe and
order-independent under the v1.19 date-aware calculation
(InventoryMovementRepository.sum_by_product_ids) with the current
codebase — not merely that it doesn't crash, but that current stock is
always exactly what the required mathematical rule says it should be
after every undo, in every order. `ImportSupersededByLaterInventoryImport`
(the old upload-order guard) is confirmed absent — grep across the
codebase turns up only historical comments, no such class/import
anywhere — undo is intentionally unconditional today; this file is the
evidence that unconditional undo is still correct, not an assumption.

Each test is numbered against the audit prompt's own Required Test
Matrix. Complements (does not duplicate) the calculation-focused
coverage in test_sales_backdating_stock_integrity.py and the direct
repository tests in test_date_aware_stock.py.
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
from app.models.import_record import ImportRecord
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


def test_import_superseded_by_later_inventory_import_guard_is_absent():
    # Delivery requirement: confirm the old upload-order guard is really
    # gone, not merely assumed gone. Importing the removed name must fail;
    # undo_import must take no order-related kwarg it could have used.
    import inspect

    from app.imports import exceptions, importer

    assert not hasattr(exceptions, "ImportSupersededByLaterInventoryImport")
    assert not hasattr(importer, "ImportSupersededByLaterInventoryImport")
    params = inspect.signature(undo_import).parameters
    assert set(params) == {"db", "import_record"}


# --- 1: sale-with-return undo — the real regression found by this audit ----


def test_1_undoing_a_backdated_sale_with_a_return_removes_everything_correctly(db_session, business_id, _fake_r2):
    """Found live during this audit: Return.sale_item_id has no
    ON DELETE CASCADE, and _undo_sales_import used to bulk-delete SaleItem
    rows without deleting their Return rows first — a real Postgres
    ForeignKeyViolation on any undo of a sales import that included a
    return, invisible in this SQLite-backed suite (which doesn't enforce
    FKs) until asserted here directly against the persisted rows, not just
    a lack of exception."""
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")

    _, record = _import_sales(
        db_session, business_id, _fake_r2,
        [
            ("2026-01-09", "Chain Lube", "CL-100", 5, "9.99", "ORD-1"),
            ("2026-01-09", "Chain Lube", "CL-100", -1, "9.99", "ORD-2"),
        ],
    )
    assert db_session.query(Return).filter(Return.business_id == business_id).count() == 1
    assert _stock(db_session, business_id, product.id) == 40  # both lines predate the count

    undone = undo_import(db_session, record)
    assert undone.status == "reversed"

    assert db_session.query(Return).filter(Return.business_id == business_id).count() == 0
    assert db_session.query(SaleItem).filter(SaleItem.business_id == business_id).count() == 0
    assert db_session.query(Sale).filter(Sale.business_id == business_id).count() == 0
    assert db_session.query(InventoryMovement).filter(
        InventoryMovement.business_id == business_id, InventoryMovement.reason.in_(("sale", "return"))
    ).count() == 0
    assert _stock(db_session, business_id, product.id) == 40  # unchanged — none of it was ever counted


# --- 2: undo a backdated purchase — cost/supplier policy ---------------------


def test_2_undoing_a_backdated_purchase_leaves_stock_unchanged_and_documents_the_cost_policy(
    db_session, business_id, _fake_r2
):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    original_cost = product.cost_price

    _, record = _import_purchases(
        db_session, business_id, _fake_r2, [("2026-01-09", "Chain Lube", "CL-100", 20, "3.50")]
    )
    assert _stock(db_session, business_id, product.id) == 40  # predates the count, excluded
    db_session.refresh(product)
    assert product.cost_price == Decimal("3.50")  # Product.cost_price is a live "current" value, updated immediately

    undone = undo_import(db_session, record)
    assert undone.status == "reversed"
    assert db_session.query(InventoryMovement).filter(
        InventoryMovement.business_id == business_id, InventoryMovement.reason == "purchase"
    ).count() == 0
    assert _stock(db_session, business_id, product.id) == 40  # still unchanged — it was never counted either way

    # Documented, existing policy (same as products auto-created by an
    # import staying in place on undo): undo removes the transactional
    # movement/reference facts, never reverse-engineers a "current state"
    # mutation like Product.cost_price back to its prior value — the same
    # reason a sale's sell_price update isn't undone either.
    db_session.refresh(product)
    assert product.cost_price == Decimal("3.50")
    assert product.cost_price != original_cost


# --- 3: undo a post-count movement — exact delta reversal --------------------


def test_3a_undoing_a_post_count_sale_restores_stock_by_exactly_its_delta(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _, record = _import_sales(db_session, business_id, _fake_r2, [("2026-01-11", "Chain Lube", "CL-100", 5, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 35

    undone = undo_import(db_session, record)
    assert undone.status == "reversed"
    assert _stock(db_session, business_id, product.id) == 40  # exactly back to the baseline, not more, not less


def test_3b_undoing_a_post_count_purchase_restores_stock_by_exactly_its_delta(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _, record = _import_purchases(db_session, business_id, _fake_r2, [("2026-01-11", "Chain Lube", "CL-100", 15, "4.00")])
    assert _stock(db_session, business_id, product.id) == 55

    undone = undo_import(db_session, record)
    assert undone.status == "reversed"
    assert _stock(db_session, business_id, product.id) == 40


# --- 4: undo an older (already-superseded) import, then the newest count ----


def test_4_undoing_an_older_import_then_the_newest_count_falls_back_correctly(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 100, "2026-01-01")], filename="c1.csv")
    product = _product(db_session, business_id, "CL-100")
    _, stale_sale_record = _import_sales(db_session, business_id, _fake_r2, [("2026-01-05", "Chain Lube", "CL-100", 10, "9.99", "ORD-1")])
    _, count2_record = _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 70, "2026-01-10")], filename="c2.csv")
    assert _stock(db_session, business_id, product.id) == 70  # count2 is the baseline; the Jan-5 sale is already superseded

    # Step 1: undo the older, already-superseded sale — a genuine no-op on current stock.
    undo_import(db_session, stale_sale_record)
    assert _stock(db_session, business_id, product.id) == 70

    # Step 2: undo the newest count — falls back to the Jan-1 count, the only one left.
    undo_import(db_session, count2_record)
    assert _stock(db_session, business_id, product.id) == 100


# --- 5: undo after an out-of-order backdated count --------------------------


def test_5_undoing_the_real_baseline_lets_a_backdated_count_take_over_correctly(db_session, business_id, _fake_r2):
    _, current_count_record = _import_inventory(
        db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 70, "2026-01-20")], filename="current.csv"
    )
    product = _product(db_session, business_id, "CL-100")
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-05", "Chain Lube", "CL-100", 5, "9.99", "ORD-1")])
    # Uploaded last, but dated earlier than the count already on file — ignored as baseline while the Jan-20 count exists.
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 999, "2026-01-06")], filename="backdated.csv")
    assert _stock(db_session, business_id, product.id) == 70

    undo_import(db_session, current_count_record)
    # The backdated count is now the only one left — it correctly becomes
    # the baseline, and the still-earlier (Jan-5) sale stays excluded
    # under it too, exactly as the date rule requires, not because of
    # upload order.
    assert _stock(db_session, business_id, product.id) == 999


# --- 6: same-day undo retains the final-stock-of-day convention -------------


def test_6a_undoing_a_same_day_sale_leaves_the_count_unaffected(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _, sale_record = _import_sales(db_session, business_id, _fake_r2, [("2026-01-10", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 40

    undo_import(db_session, sale_record)
    assert _stock(db_session, business_id, product.id) == 40  # no change either way — it was never counted


def test_6b_undoing_a_same_day_count_exposes_the_same_day_sale_correctly(db_session, business_id, _fake_r2):
    _, count_record = _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-10", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 40

    undo_import(db_session, count_record)
    # No baseline left at all now — the same-day sale (previously excluded
    # by the count) becomes an ordinary signed movement.
    assert _stock(db_session, business_id, product.id) == -3


# --- 7: undo the only count — falls back to plain signed arithmetic ---------


def test_7_undoing_the_only_count_falls_back_to_flat_signed_sum(db_session, business_id, _fake_r2):
    _, count_record = _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _import_sales(db_session, business_id, _fake_r2, [("2026-01-15", "Chain Lube", "CL-100", 6, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 34  # 40 - 6

    undo_import(db_session, count_record)
    assert _stock(db_session, business_id, product.id) == -6  # no baseline left — plain signed sum of what remains


# --- 8: undo a multi-product multi-line order --------------------------------


def test_8_undoing_a_multi_product_multi_line_order_removes_only_that_orders_data(db_session, business_id, _fake_r2):
    _, record = _import_sales(
        db_session, business_id, _fake_r2,
        [
            ("2026-01-05", "Chain Lube", "CL-100", 3, "9.99", "ORD-1"),
            ("2026-01-05", "Bar Tape", "BT-200", 2, "12.00", "ORD-1"),
        ],
    )
    lube = _product(db_session, business_id, "CL-100")
    tape = _product(db_session, business_id, "BT-200")
    assert _stock(db_session, business_id, lube.id) == -3
    assert _stock(db_session, business_id, tape.id) == -2

    undone = undo_import(db_session, record)
    assert undone.status == "reversed"
    assert db_session.query(Sale).filter(Sale.business_id == business_id).count() == 0
    assert db_session.query(SaleItem).filter(SaleItem.business_id == business_id).count() == 0
    # Both products cleanly back to zero — no partial deletion, no
    # cross-product leakage of one product's movement into the other's.
    assert _stock(db_session, business_id, lube.id) == 0
    assert _stock(db_session, business_id, tape.id) == 0


# --- 9: idempotency after undo, with a stock count in play -------------------


def test_9_reimporting_the_same_reference_after_undo_succeeds_and_stays_date_aware(db_session, business_id, _fake_r2):
    # test_importer_service.py::test_undo_then_reupload_with_the_same_order_reference_succeeds
    # already proves this without any stock count involved; this is the
    # date-aware-specific complement — re-importing after undo must still
    # correctly interact with an existing baseline, not just succeed.
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _, record = _import_sales(db_session, business_id, _fake_r2, [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 40

    undo_import(db_session, record)
    assert db_session.query(Sale).filter(Sale.business_id == business_id, Sale.order_reference == "ORD-1").count() == 0

    result2, _ = _import_sales(db_session, business_id, _fake_r2, [("2026-01-09", "Chain Lube", "CL-100", 3, "9.99", "ORD-1")], filename="reupload.csv")
    assert result2.rows_imported == 1  # not rejected as a duplicate — the earlier one was undone
    assert _stock(db_session, business_id, product.id) == 40  # still correctly excluded under the same count


# --- 10: tenant isolation on undo ---------------------------------------------


def test_10_undo_in_one_business_never_affects_another_with_identical_overlapping_data(
    db_session, business_id, _fake_r2
):
    other = Business(name="Undo Isolation Test Business")
    db_session.add(other)
    db_session.commit()
    other_id = other.id

    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")], filename="a.csv")
    _import_inventory(db_session, other_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")], filename="b.csv")
    _, record_a = _import_sales(db_session, business_id, _fake_r2, [("2026-01-11", "Chain Lube", "CL-100", 5, "9.99", "ORD-1")], filename="c.csv")
    _, record_b = _import_sales(db_session, other_id, _fake_r2, [("2026-01-11", "Chain Lube", "CL-100", 5, "9.99", "ORD-1")], filename="d.csv")

    product_a = _product(db_session, business_id, "CL-100")
    product_b = _product(db_session, other_id, "CL-100")
    assert _stock(db_session, business_id, product_a.id) == 35
    assert _stock(db_session, other_id, product_b.id) == 35

    undo_import(db_session, record_a)

    assert _stock(db_session, business_id, product_a.id) == 40  # business A's own sale reversed
    assert _stock(db_session, other_id, product_b.id) == 35  # business B completely untouched
    other_record = db_session.get(ImportRecord, record_b.id)
    assert other_record.reversed_at is None  # business B's own import record status is untouched
    assert db_session.query(Sale).filter(Sale.business_id == other_id).count() == 1  # its sale still exists


# --- 11: downstream consumers reflect the post-undo value --------------------


def test_11_downstream_consumers_reflect_the_post_undo_stock_value(db_session, business_id, _fake_r2):
    _import_inventory(db_session, business_id, _fake_r2, [("Chain Lube", "CL-100", 40, "2026-01-10")])
    product = _product(db_session, business_id, "CL-100")
    _, record = _import_sales(db_session, business_id, _fake_r2, [("2026-01-11", "Chain Lube", "CL-100", 5, "9.99", "ORD-1")])
    assert _stock(db_session, business_id, product.id) == 35

    undo_import(db_session, record)
    assert _stock(db_session, business_id, product.id) == 40

    thresholds = list_product_thresholds(db_session, business_id=business_id)
    row = next(r for r in thresholds if r.product_id == product.id)
    assert row.stock_on_hand == 40  # not 35 — the stale pre-undo value

    retail = get_retail_operations(db_session, business_id=business_id)
    cover_row = next(r for r in retail.stock_cover if r.product_id == product.id)
    assert cover_row.stock_on_hand == 40

    search_results = global_search(db_session, business_id=business_id, query="Chain Lube")
    match = next(p for p in search_results.products if p.sku == "CL-100")
    assert match.current_stock == 40


# --- 12: legacy-adjustment compatibility survives an unrelated undo ----------


def test_12_legacy_adjustment_baseline_is_unaffected_by_an_unrelated_undo(db_session, business_id, _fake_r2):
    # A legacy row (no resulting_quantity_on_hand — see
    # InventoryMovementRepository.sum_by_product_ids's own docstring)
    # written directly, the way migration 8b3e6c1a4f92's backfill would
    # have left one behind pre-event_date.
    from app.models.inventory_movement import InventoryMovement as InventoryMovementModel

    product = Product(business_id=business_id, sku="LEGACY-100", name="Legacy Product", cost_price=Decimal("5"), sell_price=Decimal("10"))
    db_session.add(product)
    db_session.flush()
    legacy = InventoryMovementModel(
        business_id=business_id, product_id=product.id, quantity_delta=100, reason="adjustment",
        event_date=date(2026, 1, 1), resulting_quantity_on_hand=None,
    )
    db_session.add(legacy)
    db_session.commit()
    assert _stock(db_session, business_id, product.id) == 100  # the legacy-compatibility fallback, not a false zero

    # An entirely unrelated import/undo cycle for a different product.
    _, unrelated_record = _import_sales(
        db_session, business_id, _fake_r2, [("2026-01-05", "Unrelated Widget", "UNREL-1", 4, "5.00", "ORD-UNREL")]
    )
    undo_import(db_session, unrelated_record)

    assert _stock(db_session, business_id, product.id) == 100  # still correct — unaffected by the unrelated undo
