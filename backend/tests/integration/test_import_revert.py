"""Undoing an import puts back what it overwrote on existing products
(app/imports/revert.py) — cost price, sell price and category — without
ever clobbering a newer import's value or a manual edit. Runs real imports
through app/imports/importer.py against a real (SQLite) database, R2
monkeypatched in-memory, same style as test_purchases_repairs_importer.py.
"""

from decimal import Decimal

import pytest

from app.imports import detection, r2_client
from app.imports.importer import run_import, undo_import
from app.models.product import Product
from app.models.product_field_change import ProductFieldChange
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.upload import UploadRepository

_PURCHASE_HEADER = ["Date", "Product", "SKU", "Qty Received", "Unit Cost"]
_PURCHASE_MAPPING = {
    "purchase_date": "Date", "product_name": "Product", "sku": "SKU",
    "quantity_received": "Qty Received", "unit_cost": "Unit Cost",
}
_SALES_HEADER = ["Date", "Product", "SKU", "Qty", "Price", "Category"]
_SALES_MAPPING = {
    "sale_date": "Date", "product_name": "Product", "sku": "SKU", "quantity": "Qty",
    "unit_price": "Price", "category": "Category",
}
_INVENTORY_HEADER = ["Product", "SKU", "Stock Level", "Cost"]
_INVENTORY_MAPPING = {"product_name": "Product", "sku": "SKU", "quantity_on_hand": "Stock Level", "unit_cost": "Cost"}


@pytest.fixture()
def _fake_r2(monkeypatch):
    store: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(store[storage_key]))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: store[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)
    return store


def _import(db_session, business_id, store, *, entity_type, header, mapping, csv, name):
    key = f"{business_id}/{name}"
    store[key] = csv.encode()
    upload = UploadRepository(db_session).create(
        business_id=business_id, storage_key=key, original_filename=name, uploaded_by="u", entity_type=entity_type
    )
    UploadRepository(db_session).set_status(upload, status="uploaded")
    profile = ImportMappingProfileRepository(db_session).upsert(
        business_id=business_id, source_signature=detection.compute_source_signature(entity_type, header) + name,
        column_mapping={"entity_type": entity_type, "engine_version": 1, "fields": mapping},
    )
    record = ImportRecordRepository(db_session).create(
        business_id=business_id, upload_id=upload.id, mapping_profile_id=profile.id, entity_type=entity_type, status="mapped"
    )
    upload = UploadRepository(db_session).set_status(upload, status="mapped")
    run_import(db_session, upload, record)
    return db_session.get(type(record), record.id)


def _purchase(db_session, business_id, store, name, rows):
    csv = "Date,Product,SKU,Qty Received,Unit Cost\n" + "".join(f"2026-01-05,{p},{s},10,{c}\n" for p, s, c in rows)
    return _import(db_session, business_id, store, entity_type="purchases", header=_PURCHASE_HEADER,
                   mapping=_PURCHASE_MAPPING, csv=csv, name=name)


def _product(db_session, business_id, sku, cost, sell=None, category_id=None):
    p = ProductRepository(db_session).create(
        business_id=business_id, sku=sku, name=f"Product {sku}", cost_price=Decimal(cost) if cost is not None else None,
        sell_price=Decimal(sell) if sell is not None else None, category_id=category_id,
    )
    db_session.commit()
    return p


def _live(db_session, product_id):
    db_session.expire_all()
    return db_session.get(Product, product_id)


def test_undoing_a_purchase_file_restores_the_cost_it_overwrote(db_session, business_id, _fake_r2):
    product = _product(db_session, business_id, "CL-100", "4.00")
    record = _purchase(db_session, business_id, _fake_r2, "p1.csv", [("Chain Lube", "CL-100", "9.99")])
    assert _live(db_session, product.id).cost_price == Decimal("9.99")

    undo_import(db_session, record)

    assert _live(db_session, product.id).cost_price == Decimal("4.00")


def test_re_importing_the_same_price_records_no_change(db_session, business_id, _fake_r2):
    product = _product(db_session, business_id, "CL-100", "4.00")
    _purchase(db_session, business_id, _fake_r2, "p1.csv", [("Chain Lube", "CL-100", "4.0")])  # numerically the same

    assert db_session.query(ProductFieldChange).filter_by(product_id=product.id).count() == 0


def test_a_product_the_import_created_is_left_in_place_by_undo(db_session, business_id, _fake_r2):
    record = _purchase(db_session, business_id, _fake_r2, "p1.csv", [("Brand New", "NEW-1", "7.50")])
    undo_import(db_session, record)

    created = db_session.query(Product).filter_by(business_id=business_id, sku="NEW-1").one()
    assert created.cost_price == Decimal("7.50")  # unchanged long-standing behaviour: created products stay


def test_undoing_the_older_file_while_a_newer_one_is_active_keeps_the_newer_value_then_lands_on_the_original(
    db_session, business_id, _fake_r2
):
    product = _product(db_session, business_id, "CL-100", "4.00")
    file_a = _purchase(db_session, business_id, _fake_r2, "a.csv", [("Chain Lube", "CL-100", "5.00")])
    file_b = _purchase(db_session, business_id, _fake_r2, "b.csv", [("Chain Lube", "CL-100", "6.00")])

    undo_import(db_session, file_a)  # B is still in effect
    assert _live(db_session, product.id).cost_price == Decimal("6.00")  # B's value is not clobbered

    undo_import(db_session, file_b)
    # Lands on the true original, NOT on A's 5.00 (A's file no longer counts).
    assert _live(db_session, product.id).cost_price == Decimal("4.00")


def test_undoing_newest_first_then_oldest_walks_back_to_the_original(db_session, business_id, _fake_r2):
    product = _product(db_session, business_id, "CL-100", "4.00")
    file_a = _purchase(db_session, business_id, _fake_r2, "a.csv", [("Chain Lube", "CL-100", "5.00")])
    file_b = _purchase(db_session, business_id, _fake_r2, "b.csv", [("Chain Lube", "CL-100", "6.00")])

    undo_import(db_session, file_b)
    assert _live(db_session, product.id).cost_price == Decimal("5.00")
    undo_import(db_session, file_a)
    assert _live(db_session, product.id).cost_price == Decimal("4.00")


def test_a_manual_edit_made_after_the_import_is_never_reverted(db_session, business_id, _fake_r2):
    product = _product(db_session, business_id, "CL-100", "4.00")
    record = _purchase(db_session, business_id, _fake_r2, "a.csv", [("Chain Lube", "CL-100", "5.00")])
    live = _live(db_session, product.id)
    live.cost_price = Decimal("8.88")  # someone fixed it by hand
    db_session.commit()

    undo_import(db_session, record)

    assert _live(db_session, product.id).cost_price == Decimal("8.88")
    change = db_session.query(ProductFieldChange).filter_by(import_record_id=record.id).one()
    assert change.status == "kept_edited"


def test_the_same_product_twice_in_one_file_unwinds_to_the_original(db_session, business_id, _fake_r2):
    product = _product(db_session, business_id, "CL-100", "4.00")
    record = _purchase(
        db_session, business_id, _fake_r2, "dup.csv", [("Chain Lube", "CL-100", "5.00"), ("Chain Lube", "CL-100", "6.00")]
    )
    assert _live(db_session, product.id).cost_price == Decimal("6.00")

    undo_import(db_session, record)

    assert _live(db_session, product.id).cost_price == Decimal("4.00")


def test_undoing_a_sales_file_restores_sell_price_and_category(db_session, business_id, _fake_r2):
    old_category = ProductCategoryRepository(db_session).create(business_id=business_id, name="Old Cat")
    product = _product(db_session, business_id, "CL-100", "4.00", sell="10.00", category_id=old_category.id)
    csv = "Date,Product,SKU,Qty,Price,Category\n2026-01-05,Chain Lube,CL-100,1,19.99,New Cat\n"
    record = _import(db_session, business_id, _fake_r2, entity_type="sales", header=_SALES_HEADER, mapping=_SALES_MAPPING, csv=csv, name="s.csv")
    live = _live(db_session, product.id)
    assert live.sell_price == Decimal("19.99") and live.category_id != old_category.id

    undo_import(db_session, record)

    live = _live(db_session, product.id)
    assert live.sell_price == Decimal("10.00")
    assert live.category_id == old_category.id


def test_a_category_set_where_there_was_none_reverts_to_none(db_session, business_id, _fake_r2):
    product = _product(db_session, business_id, "CL-100", "4.00", sell="10.00", category_id=None)
    csv = "Date,Product,SKU,Qty,Price,Category\n2026-01-05,Chain Lube,CL-100,1,10.00,Brand New Cat\n"
    record = _import(db_session, business_id, _fake_r2, entity_type="sales", header=_SALES_HEADER, mapping=_SALES_MAPPING, csv=csv, name="s.csv")
    assert _live(db_session, product.id).category_id is not None

    undo_import(db_session, record)

    assert _live(db_session, product.id).category_id is None


def test_undoing_a_stock_count_restores_the_cost_it_overwrote(db_session, business_id, _fake_r2):
    product = _product(db_session, business_id, "CL-100", "4.00")
    csv = "Product,SKU,Stock Level,Cost\nChain Lube,CL-100,25,12.50\n"
    record = _import(db_session, business_id, _fake_r2, entity_type="inventory", header=_INVENTORY_HEADER, mapping=_INVENTORY_MAPPING, csv=csv, name="i.csv")
    assert _live(db_session, product.id).cost_price == Decimal("12.50")

    undo_import(db_session, record)

    assert _live(db_session, product.id).cost_price == Decimal("4.00")


def test_changes_are_tenant_scoped_one_businesss_undo_never_touches_anothers_product(db_session, business_id, _fake_r2):
    from app.models.business import Business

    other = Business(name="Other Shop")
    db_session.add(other)
    db_session.commit()
    mine = _product(db_session, business_id, "CL-100", "4.00")
    theirs = _product(db_session, other.id, "CL-100", "4.00")  # same SKU, different tenant
    record = _purchase(db_session, business_id, _fake_r2, "a.csv", [("Chain Lube", "CL-100", "9.00")])
    assert _live(db_session, theirs.id).cost_price == Decimal("4.00")  # never touched by the import

    undo_import(db_session, record)

    assert _live(db_session, mine.id).cost_price == Decimal("4.00")
    assert _live(db_session, theirs.id).cost_price == Decimal("4.00")
