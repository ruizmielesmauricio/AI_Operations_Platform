import pytest
from sqlalchemy import select

from app.imports import r2_client
from app.imports.exceptions import InvalidHeaderRowIndex
from app.imports.importer import run_import
from app.imports.service import confirm_mapping, detect_mapping_for_upload
from app.models.sale import Sale
from app.repositories.upload import UploadRepository

_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price"]
# 20 junk rows push the real header past detect_header_row's 0-14 search
# window, guaranteeing auto-detection fails — exactly the case the manual
# picker exists for.
_JUNK_ROWS = "\n".join(f"Junk row {i}" for i in range(20))
_CSV_CONTENT = (
    f"{_JUNK_ROWS}\n"
    "Order Date,Item Description,SKU,Qty,Unit Price\n"
    "2026-01-03,Chain Lube,CL-100,3,9.99\n"
    "2026-01-04,Bar Tape,BT-200,1,12.00\n"
).encode()

_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
    "total_amount": None,
    "cost_price_at_sale": None,
    "tax_amount": None,
    "order_reference": None,
}


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(_CSV_CONTENT))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: _CSV_CONTENT)
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: None)


def _make_uploaded(db_session, business_id, filename="sales.csv"):
    upload = UploadRepository(db_session).create(
        business_id=business_id,
        storage_key=f"{business_id}/test/{filename}",
        original_filename=filename,
        uploaded_by="user-a",
        entity_type="sales",
    )
    return UploadRepository(db_session).set_status(upload, status="uploaded")


def test_detect_mapping_returns_preview_rows_when_auto_detection_fails(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)

    result = detect_mapping_for_upload(db_session, upload)

    assert result.status == "header_not_found"
    assert result.preview_rows is not None
    assert result.preview_rows[0][0] == "Junk row 0"
    # Wider than the 15-row auto-search window on purpose — the real
    # header (index 20) must actually be visible to pick, not just rows
    # auto-detection already ruled out.
    assert result.preview_rows[20][0] == "Order Date"


def test_manual_header_pick_then_confirm_then_import_end_to_end(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)

    # Step 1: auto-detection fails.
    first = detect_mapping_for_upload(db_session, upload)
    assert first.status == "header_not_found"

    # Step 2: user picks the real header row (index 20) — real header index
    # is len(junk rows) == 20, computed the same way the test data was built.
    header_row_index = 20
    second = detect_mapping_for_upload(db_session, upload, header_row_index)
    assert second.status == "needs_confirmation"
    assert second.suggested_mapping["sale_date"] == "Order Date"

    # Step 3: confirm, passing the same header_row_index through.
    record, profile_id = confirm_mapping(db_session, upload, _FIELD_MAPPING, header_row_index)
    assert record.status == "mapped"

    upload = UploadRepository(db_session).get_for_business(upload.id, business_id)

    # Step 4: run the import — this is the critical case: importer.py's own
    # auto-detection will ALSO fail on this file (nothing about the file
    # changed), so it must fall back to the header_row_index stored at
    # confirm-mapping time rather than failing identically every time.
    result = run_import(db_session, upload, record)

    assert result.status == "completed"
    assert result.rows_imported == 2
    sales = db_session.scalars(select(Sale).where(Sale.business_id == business_id)).all()
    assert len(sales) == 2


def test_detect_mapping_with_manual_index_rejects_out_of_range(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)
    with pytest.raises(InvalidHeaderRowIndex):
        detect_mapping_for_upload(db_session, upload, 9999)
