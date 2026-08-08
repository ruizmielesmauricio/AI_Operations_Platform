"""Covers the new "category" optional field on sales/purchases/inventory
uploads, and purchases' unit_cost now also being written onto the
InventoryMovement row itself (not just Product.cost_price) — end to end
through the real run_import pipeline. Mirrors
tests/integration/test_purchases_repairs_importer.py's helper conventions
(a mapped upload built directly, bypassing the HTTP layer, matching this
codebase's established integration-test style for importer behavior).
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.imports import detection, r2_client
from app.imports.importer import run_import
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product, ProductCategory
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.upload import UploadRepository

_PURCHASE_HEADER = ["Date", "Product", "SKU", "Qty Received", "Unit Cost", "Category"]
_PURCHASE_FIELD_MAPPING = {
    "purchase_date": "Date",
    "product_name": "Product",
    "sku": "SKU",
    "quantity_received": "Qty Received",
    "unit_cost": "Unit Cost",
    "category": "Category",
}


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
        business_id=business_id, storage_key=storage_key, original_filename=filename,
        uploaded_by="user-a", entity_type=entity_type,
    )
    upload = UploadRepository(db_session).set_status(upload, status="uploaded")

    signature = detection.compute_source_signature(entity_type, header)
    profile = ImportMappingProfileRepository(db_session).upsert(
        business_id=business_id, source_signature=signature,
        column_mapping={"entity_type": entity_type, "engine_version": 1, "fields": field_mapping},
    )
    record = ImportRecordRepository(db_session).create(
        business_id=business_id, upload_id=upload.id, mapping_profile_id=profile.id,
        entity_type=entity_type, status="mapped",
    )
    upload = UploadRepository(db_session).set_status(upload, status="mapped")
    return upload, record


def _make_purchase_upload(db_session, business_id, content_by_key, content, filename="purchases.csv"):
    return _make_mapped_upload(
        db_session, business_id, content_by_key,
        entity_type="purchases", header=_PURCHASE_HEADER, content=content, filename=filename,
        field_mapping=_PURCHASE_FIELD_MAPPING,
    )


def test_category_is_auto_created_and_assigned_to_a_new_product(db_session, business_id, _fake_r2):
    content = (
        "Date,Product,SKU,Qty Received,Unit Cost,Category\n"
        "2026-01-05,Chain Lube,CL-100,50,4.75,Consumables\n"
    ).encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content)

    run_import(db_session, upload, record)

    category = db_session.scalar(select(ProductCategory).where(ProductCategory.business_id == business_id))
    assert category is not None
    assert category.name == "Consumables"

    product = db_session.scalar(select(Product).where(Product.sku == "CL-100"))
    assert product.category_id == category.id


def test_category_matching_is_case_and_whitespace_insensitive_no_duplicate_created(db_session, business_id, _fake_r2):
    content = (
        "Date,Product,SKU,Qty Received,Unit Cost,Category\n"
        "2026-01-05,Chain Lube,CL-100,10,4.75,Consumables\n"
        "2026-01-06,Bar Tape,BT-200,5,3.00, consumables \n"
    ).encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content)

    run_import(db_session, upload, record)

    categories = list(db_session.scalars(select(ProductCategory).where(ProductCategory.business_id == business_id)))
    assert len(categories) == 1
    assert categories[0].name == "Consumables"


def test_category_is_overwritten_on_a_later_sighting_of_an_existing_product(db_session, business_id, _fake_r2):
    # Row 1 creates the product under "Consumables"; row 2 (a later
    # purchase of the same SKU) maps a different category — matches
    # ProductRepository.update_cost_price's "latest wins" precedent.
    content = (
        "Date,Product,SKU,Qty Received,Unit Cost,Category\n"
        "2026-01-05,Chain Lube,CL-100,50,4.75,Consumables\n"
        "2026-02-01,Chain Lube,CL-100,20,4.80,Lubricants\n"
    ).encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content)

    run_import(db_session, upload, record)

    product = db_session.scalar(select(Product).where(Product.sku == "CL-100"))
    category = db_session.scalar(select(ProductCategory).where(ProductCategory.id == product.category_id))
    assert category.name == "Lubricants"
    # Both categories exist — the earlier one wasn't deleted, just no
    # longer referenced by this product.
    all_names = {
        c.name for c in db_session.scalars(select(ProductCategory).where(ProductCategory.business_id == business_id))
    }
    assert all_names == {"Consumables", "Lubricants"}


def test_a_row_with_no_category_mapped_leaves_an_existing_product_s_category_untouched(db_session, business_id, _fake_r2):
    content = (
        "Date,Product,SKU,Qty Received,Unit Cost,Category\n"
        "2026-01-05,Chain Lube,CL-100,50,4.75,Consumables\n"
        "2026-02-01,Chain Lube,CL-100,20,4.80,\n"
    ).encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content)

    run_import(db_session, upload, record)

    product = db_session.scalar(select(Product).where(Product.sku == "CL-100"))
    category = db_session.scalar(select(ProductCategory).where(ProductCategory.id == product.category_id))
    assert category.name == "Consumables"


def test_purchase_row_with_unit_cost_writes_it_onto_the_movement_row(db_session, business_id, _fake_r2):
    content = "Date,Product,SKU,Qty Received,Unit Cost,Category\n2026-01-05,Chain Lube,CL-100,50,4.75,\n".encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content)

    run_import(db_session, upload, record)

    movement = db_session.scalar(
        select(InventoryMovement).where(InventoryMovement.business_id == business_id, InventoryMovement.reason == "purchase")
    )
    assert movement.unit_cost == pytest.approx(4.75) or str(movement.unit_cost) == "4.75"


def test_purchase_row_with_no_unit_cost_leaves_the_movement_row_s_unit_cost_null(db_session, business_id, _fake_r2):
    content = "Date,Product,SKU,Qty Received,Unit Cost,Category\n2026-01-05,Bar Tape,BT-200,20,,\n".encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content)

    run_import(db_session, upload, record)

    movement = db_session.scalar(
        select(InventoryMovement).where(InventoryMovement.business_id == business_id, InventoryMovement.reason == "purchase")
    )
    assert movement.unit_cost is None


def test_aggregate_purchase_cost_by_product_in_range_sums_known_cost_rows_only(db_session, business_id, _fake_r2):
    content = (
        "Date,Product,SKU,Qty Received,Unit Cost,Category\n"
        "2026-01-05,Chain Lube,CL-100,10,4.00,\n"
        "2026-01-06,Chain Lube,CL-100,5,,\n"  # no cost this time
    ).encode()
    upload, record = _make_purchase_upload(db_session, business_id, _fake_r2, content)
    run_import(db_session, upload, record)

    product = db_session.scalar(select(Product).where(Product.sku == "CL-100"))
    aggregates = InventoryMovementRepository(db_session).aggregate_purchase_cost_by_product_in_range(
        business_id, date(2026, 1, 1), date(2026, 1, 31)
    )
    agg = next(a for a in aggregates if a.product_id == product.id)
    assert agg.quantity_received == 15
    assert agg.quantity_received_with_known_cost == 10
    assert agg.cost == 40  # 10 * 4.00, the 5-unit unknown-cost row excluded
