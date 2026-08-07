"""Covers a real bug found live while verifying the category-breakdown
feature against real Gate B data: every one of 180 real products had
Product.sell_price = NULL, because it was only ever set once, at
product-creation time in _write_sales — a product first created via
"purchases"/"inventory" (no price concept in those rows) never got a
sell_price at all, even once it was later actually sold. Fixed by
ProductRepository.update_sell_price, called from _write_sales on every
existing-product sighting (mirrors update_cost_price's own "latest wins"
precedent, which had the identical gap until v1.11).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.imports import detection, r2_client
from app.imports.importer import run_import
from app.models.product import Product
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.upload import UploadRepository

_SALES_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price"]
_SALES_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
}


@pytest.fixture()
def _fake_r2(monkeypatch):
    content_by_key: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(content_by_key[storage_key]))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: content_by_key[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)
    return content_by_key


def _make_sales_upload(db_session, business_id, content_by_key, content, filename="sales.csv"):
    storage_key = f"{business_id}/test/{filename}"
    content_by_key[storage_key] = content

    upload = UploadRepository(db_session).create(
        business_id=business_id, storage_key=storage_key, original_filename=filename,
        uploaded_by="user-a", entity_type="sales",
    )
    upload = UploadRepository(db_session).set_status(upload, status="uploaded")

    signature = detection.compute_source_signature("sales", _SALES_HEADER)
    profile = ImportMappingProfileRepository(db_session).upsert(
        business_id=business_id, source_signature=signature,
        column_mapping={"entity_type": "sales", "engine_version": 1, "fields": _SALES_FIELD_MAPPING},
    )
    record = ImportRecordRepository(db_session).create(
        business_id=business_id, upload_id=upload.id, mapping_profile_id=profile.id,
        entity_type="sales", status="mapped",
    )
    upload = UploadRepository(db_session).set_status(upload, status="mapped")
    return upload, record


def test_selling_a_product_first_created_with_no_sell_price_backfills_it(db_session, business_id, _fake_r2):
    # Mirrors how a real product created via a "purchases"/"inventory"
    # upload has no sell_price concept at creation time.
    product = Product(
        business_id=business_id, sku="CL-100", name="Chain Lube", cost_price=Decimal("4.00"), sell_price=None,
    )
    db_session.add(product)
    db_session.commit()

    content = "Order Date,Item Description,SKU,Qty,Unit Price\n2026-01-05,Chain Lube,CL-100,3,9.99\n".encode()
    upload, record = _make_sales_upload(db_session, business_id, _fake_r2, content)

    run_import(db_session, upload, record)

    db_session.refresh(product)
    assert product.sell_price == Decimal("9.99")


def test_a_later_price_change_overwrites_the_previous_sell_price(db_session, business_id, _fake_r2):
    product = Product(
        business_id=business_id, sku="CL-100", name="Chain Lube", cost_price=Decimal("4.00"), sell_price=Decimal("8.99"),
    )
    db_session.add(product)
    db_session.commit()

    content = "Order Date,Item Description,SKU,Qty,Unit Price\n2026-02-01,Chain Lube,CL-100,1,10.99\n".encode()
    upload, record = _make_sales_upload(db_session, business_id, _fake_r2, content, filename="sales2.csv")

    run_import(db_session, upload, record)

    db_session.refresh(product)
    assert product.sell_price == Decimal("10.99")
