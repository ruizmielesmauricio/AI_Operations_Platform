import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.exceptions import ImportSupersededByLaterInventoryImport
from app.imports.importer import run_import, undo_import
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.production_event import ProductionEvent
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.product import ProductRepository
from app.repositories.upload import UploadRepository

_PURCHASE_HEADER = ["Date", "Product", "SKU", "Qty Received", "Unit Cost"]
_PURCHASE_CSV = (
    "Date,Product,SKU,Qty Received,Unit Cost\n"
    "2026-01-05,Chain Lube,CL-100,50,4.75\n"
    "2026-01-05,Bar Tape,BT-200,20,\n"
).encode()
_PURCHASE_FIELD_MAPPING = {
    "purchase_date": "Date",
    "product_name": "Product",
    "sku": "SKU",
    "quantity_received": "Qty Received",
    "unit_cost": "Unit Cost",
}

_REPAIR_HEADER = ["Date", "Description", "Price Charged", "Labour Cost"]
_REPAIR_CSV = (
    "Date,Description,Price Charged,Labour Cost\n"
    "2026-01-05,Replaced brake pads,45.00,20.00\n"
    "2026-01-06,Fixed a puncture,15.00,\n"
).encode()
_REPAIR_FIELD_MAPPING = {
    "repair_date": "Date",
    "description": "Description",
    "price_charged": "Price Charged",
    "labour_cost": "Labour Cost",
}

_INVENTORY_FIELD_MAPPING = {"product_name": "Product", "sku": "SKU", "quantity_on_hand": "Stock Level"}


@pytest.fixture()
def _fake_r2(monkeypatch):
    content_by_key: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(content_by_key[storage_key]))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: content_by_key[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)
    return content_by_key


def _make_mapped_upload(db_session, business_id, content_by_key, *, entity_type, header, content, filename, field_mapping):
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


def _make_purchase_upload(db_session, business_id, content_by_key, filename="purchases.csv", content=_PURCHASE_CSV):
    return _make_mapped_upload(
        db_session, business_id, content_by_key,
        entity_type="purchases", header=_PURCHASE_HEADER, content=content, filename=filename,
        field_mapping=_PURCHASE_FIELD_MAPPING,
    )


def _make_repair_upload(db_session, business_id, content_by_key, filename="repairs.csv", content=_REPAIR_CSV):
    return _make_mapped_upload(
        db_session, business_id, content_by_key,
        entity_type="repairs", header=_REPAIR_HEADER, content=content, filename=filename,
        field_mapping=_REPAIR_FIELD_MAPPING,
    )


def _make_inventory_upload(db_session, business_id, content_by_key, filename, content):
    return _make_mapped_upload(
        db_session, business_id, content_by_key,
        entity_type="inventory", header=["Product", "SKU", "Stock Level"], content=content, filename=filename,
        field_mapping=_INVENTORY_FIELD_MAPPING,
    )


# --- purchases --------------------------------------------------------


def test_purchase_import_writes_purchase_movements_and_seeds_cost_on_create(db_session, business_id, _fake_r2):
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2)

    result = run_import(db_session, upload, record)

    assert result.status == "completed"
    assert result.rows_imported == 2
    assert result.rows_rejected == 0

    movements = db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all()
    assert len(movements) == 2
    assert all(m.reason == "purchase" for m in movements)
    assert all(m.import_record_id == record.id for m in movements)
    assert sorted(m.quantity_delta for m in movements) == [20, 50]

    chain_lube = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "CL-100"))
    bar_tape = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "BT-200"))
    assert chain_lube.cost_price == Decimal("4.75")  # seeded from unit_cost on auto-create
    assert bar_tape.cost_price is None  # no unit_cost given for this row
    assert chain_lube.sell_price is None  # a purchase never states a sell price


def test_purchase_import_overwrites_existing_product_s_cost_price(db_session, business_id, _fake_r2):
    ProductRepository(db_session).create(
        business_id=business_id, sku="CL-100", name="Chain Lube", cost_price=Decimal("3.00"), sell_price=Decimal("9.99")
    )
    db_session.commit()

    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload, record)

    product = db_session.scalar(select(Product).where(Product.business_id == business_id, Product.sku == "CL-100"))
    assert product.cost_price == Decimal("4.75")  # unconditionally overwritten by the newer purchase price
    assert product.sell_price == Decimal("9.99")  # untouched — a purchase never states a sell price


def test_purchase_row_with_non_positive_quantity_is_rejected(db_session, business_id, _fake_r2):
    content = "Date,Product,SKU,Qty Received,Unit Cost\n2026-01-05,Chain Lube,CL-100,0,4.75\n".encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content=content)

    result = run_import(db_session, upload, record)

    assert result.rows_imported == 0
    assert result.rows_rejected == 1
    assert result.rejection_summary["reasons"]["non_positive_quantity"]["count"] == 1


def test_undo_purchase_import_bulk_deletes_by_import_record_id(db_session, business_id, _fake_r2):
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload, record)
    assert db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all()

    undone = undo_import(db_session, record)

    assert undone.status == "reversed"
    assert db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all() == []
    # Products auto-created by this import are deliberately left in place,
    # same precedent as sales/inventory — including the cost_price it seeded.
    products = db_session.scalars(select(Product).where(Product.business_id == business_id)).all()
    assert products
    assert any(p.cost_price == Decimal("4.75") for p in products)


def test_purchase_row_reusing_a_reference_from_an_earlier_import_is_rejected(db_session, business_id, _fake_r2):
    content = "Date,Product,SKU,Qty Received,Unit Cost,PO Number\n2026-01-05,Chain Lube,CL-100,50,4.75,PO-1\n".encode()
    field_mapping = {**_PURCHASE_FIELD_MAPPING, "purchase_reference": "PO Number"}
    upload1, record1 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="purchases", header=["Date", "Product", "SKU", "Qty Received", "Unit Cost", "PO Number"],
        content=content, filename="a.csv", field_mapping=field_mapping,
    )
    run_import(db_session, upload1, record1)

    upload2, record2 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="purchases", header=["Date", "Product", "SKU", "Qty Received", "Unit Cost", "PO Number"],
        content=content, filename="b.csv", field_mapping=field_mapping,
    )
    result = run_import(db_session, upload2, record2)

    assert result.rows_imported == 0
    assert result.rows_rejected == 1
    assert result.rejection_summary["reasons"]["duplicate_reference"]["count"] == 1

    movements = db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all()
    assert len(movements) == 1  # nothing new written — no double-counted stock


def test_purchase_rows_sharing_a_reference_within_one_file_second_row_is_rejected(db_session, business_id, _fake_r2):
    content = (
        "Date,Product,SKU,Qty Received,Unit Cost,PO Number\n"
        "2026-01-05,Chain Lube,CL-100,50,4.75,PO-1\n"
        "2026-01-06,Bar Tape,BT-200,20,3.00,PO-1\n"
    ).encode()
    field_mapping = {**_PURCHASE_FIELD_MAPPING, "purchase_reference": "PO Number"}
    upload, record = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="purchases", header=["Date", "Product", "SKU", "Qty Received", "Unit Cost", "PO Number"],
        content=content, filename="a.csv", field_mapping=field_mapping,
    )

    result = run_import(db_session, upload, record)

    assert result.rows_imported == 1
    assert result.rows_rejected == 1
    assert result.rejection_summary["reasons"]["duplicate_reference"]["count"] == 1


def test_undo_then_reupload_a_purchase_with_the_same_reference_succeeds(db_session, business_id, _fake_r2):
    content = "Date,Product,SKU,Qty Received,Unit Cost,PO Number\n2026-01-05,Chain Lube,CL-100,50,4.75,PO-1\n".encode()
    field_mapping = {**_PURCHASE_FIELD_MAPPING, "purchase_reference": "PO Number"}
    header = ["Date", "Product", "SKU", "Qty Received", "Unit Cost", "PO Number"]
    upload1, record1 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="purchases", header=header, content=content, filename="a.csv", field_mapping=field_mapping,
    )
    run_import(db_session, upload1, record1)

    undone = undo_import(db_session, record1)
    assert undone.status == "reversed"

    upload2, record2 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="purchases", header=header, content=content, filename="b.csv", field_mapping=field_mapping,
    )
    result = run_import(db_session, upload2, record2)

    assert result.rows_imported == 1  # succeeds exactly as the first import did


def test_undoing_a_purchase_import_is_blocked_by_a_later_inventory_reconciliation(db_session, business_id, _fake_r2):
    """Same hazard class as sales: a purchase movement is order-independent
    on its own, but can still be retroactively baked into a later inventory
    reconciliation's snapshot — the existing global guard must catch this
    without any purchases-specific logic."""
    purchase_content = "Date,Product,SKU,Qty Received,Unit Cost\n2026-01-05,Chain Lube,CL-100,50,4.75\n".encode()
    upload1, purchase_record = _make_purchase_upload(db_session, business_id, _fake_r2, content=purchase_content)
    run_import(db_session, upload1, purchase_record)

    inventory_content = "Product,SKU,Stock Level\nChain Lube,CL-100,40\n".encode()
    upload2, inventory_record = _make_inventory_upload(
        db_session, business_id, _fake_r2, filename="stock.csv", content=inventory_content
    )
    run_import(db_session, upload2, inventory_record)

    with pytest.raises(ImportSupersededByLaterInventoryImport):
        undo_import(db_session, purchase_record)


# --- repairs ------------------------------------------------------------


def test_repair_import_creates_completed_production_events_with_no_stock_impact(db_session, business_id, _fake_r2):
    upload, record = _make_repair_upload(db_session, business_id, _fake_r2)

    result = run_import(db_session, upload, record)

    assert result.status == "completed"
    assert result.rows_imported == 2
    assert result.rows_rejected == 0

    events = db_session.scalars(select(ProductionEvent).where(ProductionEvent.business_id == business_id)).all()
    assert len(events) == 2
    assert all(e.event_type == "repair" for e in events)
    assert all(e.status == "completed" for e in events)
    assert all(e.completed_at is not None for e in events)
    assert all(e.import_record_id == record.id for e in events)
    # v1 has no matching infrastructure — same data-minimisation precedent
    # as sales never getting customer_id.
    assert all(e.customer_id is None and e.performed_by_id is None for e in events)

    # No InventoryMovement at all — repairs don't capture parts-consumed
    # detail in v1.
    assert db_session.scalars(select(InventoryMovement).where(InventoryMovement.business_id == business_id)).all() == []


def test_repair_row_with_no_detail_is_rejected(db_session, business_id, _fake_r2):
    content = "Date,Description,Price Charged,Labour Cost\n2026-01-05,,,\n".encode()
    upload, record = _make_repair_upload(db_session, business_id, _fake_r2, content=content)

    result = run_import(db_session, upload, record)

    assert result.rows_imported == 0
    assert result.rows_rejected == 1
    assert result.rejection_summary["reasons"]["missing_repair_detail"]["count"] == 1


def test_undo_repair_import_bulk_deletes_events_and_touches_no_products(db_session, business_id, _fake_r2):
    upload, record = _make_repair_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload, record)
    assert db_session.scalars(select(ProductionEvent).where(ProductionEvent.business_id == business_id)).all()

    undone = undo_import(db_session, record)

    assert undone.status == "reversed"
    assert db_session.scalars(select(ProductionEvent).where(ProductionEvent.business_id == business_id)).all() == []


def test_repair_row_reusing_a_reference_from_an_earlier_import_is_rejected(db_session, business_id, _fake_r2):
    content = (
        "Date,Description,Price Charged,Labour Cost,Job Number\n"
        "2026-01-05,Replaced brake pads,45.00,20.00,JOB-1\n"
    ).encode()
    field_mapping = {**_REPAIR_FIELD_MAPPING, "repair_reference": "Job Number"}
    header = ["Date", "Description", "Price Charged", "Labour Cost", "Job Number"]
    upload1, record1 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="repairs", header=header, content=content, filename="a.csv", field_mapping=field_mapping,
    )
    run_import(db_session, upload1, record1)

    upload2, record2 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="repairs", header=header, content=content, filename="b.csv", field_mapping=field_mapping,
    )
    result = run_import(db_session, upload2, record2)

    assert result.rows_imported == 0
    assert result.rows_rejected == 1
    assert result.rejection_summary["reasons"]["duplicate_reference"]["count"] == 1

    events = db_session.scalars(select(ProductionEvent).where(ProductionEvent.business_id == business_id)).all()
    assert len(events) == 1  # nothing new written — no double-counted workshop revenue


def test_repair_rows_sharing_a_reference_within_one_file_second_row_is_rejected(db_session, business_id, _fake_r2):
    content = (
        "Date,Description,Price Charged,Labour Cost,Job Number\n"
        "2026-01-05,Replaced brake pads,45.00,20.00,JOB-1\n"
        "2026-01-06,Fixed a puncture,15.00,,JOB-1\n"
    ).encode()
    field_mapping = {**_REPAIR_FIELD_MAPPING, "repair_reference": "Job Number"}
    header = ["Date", "Description", "Price Charged", "Labour Cost", "Job Number"]
    upload, record = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="repairs", header=header, content=content, filename="a.csv", field_mapping=field_mapping,
    )

    result = run_import(db_session, upload, record)

    assert result.rows_imported == 1
    assert result.rows_rejected == 1
    assert result.rejection_summary["reasons"]["duplicate_reference"]["count"] == 1


def test_undo_then_reupload_a_repair_with_the_same_reference_succeeds(db_session, business_id, _fake_r2):
    content = (
        "Date,Description,Price Charged,Labour Cost,Job Number\n"
        "2026-01-05,Replaced brake pads,45.00,20.00,JOB-1\n"
    ).encode()
    field_mapping = {**_REPAIR_FIELD_MAPPING, "repair_reference": "Job Number"}
    header = ["Date", "Description", "Price Charged", "Labour Cost", "Job Number"]
    upload1, record1 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="repairs", header=header, content=content, filename="a.csv", field_mapping=field_mapping,
    )
    run_import(db_session, upload1, record1)

    undone = undo_import(db_session, record1)
    assert undone.status == "reversed"

    upload2, record2 = _make_mapped_upload(
        db_session, business_id, _fake_r2,
        entity_type="repairs", header=header, content=content, filename="b.csv", field_mapping=field_mapping,
    )
    result = run_import(db_session, upload2, record2)

    assert result.rows_imported == 1  # succeeds exactly as the first import did


def test_undoing_a_repair_import_is_never_blocked_by_a_later_inventory_reconciliation(db_session, business_id, _fake_r2):
    # Repairs write no InventoryMovement at all, so the global undo-guard
    # (has_later_completed_inventory_import) is a harmless no-op for it.
    upload1, repair_record = _make_repair_upload(db_session, business_id, _fake_r2)
    run_import(db_session, upload1, repair_record)

    inventory_content = "Product,SKU,Stock Level\nChain Lube,CL-100,40\n".encode()
    upload2, inventory_record = _make_inventory_upload(
        db_session, business_id, _fake_r2, filename="stock.csv", content=inventory_content
    )
    run_import(db_session, upload2, inventory_record)

    undone = undo_import(db_session, repair_record)
    assert undone.status == "reversed"


# --- ProductRepository.update_cost_price (direct) ------------------------


def test_update_cost_price_returns_none_for_a_product_in_another_business(db_session, business_id):
    other_business_product_id = uuid.uuid4()
    result = ProductRepository(db_session).update_cost_price(
        business_id=business_id, product_id=other_business_product_id, cost_price=Decimal("1.00")
    )
    assert result is None
