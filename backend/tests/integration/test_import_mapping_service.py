import pytest
from sqlalchemy import select

from app.imports import detection, r2_client, service
from app.imports.exceptions import InsufficientMapping, InvalidFieldMapping, UploadNotReady
from app.models.import_record import ImportMappingProfile
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.upload import UploadRepository

_HEADER = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price"]
_CSV_CONTENT = (
    "Order Date,Item Description,SKU,Qty,Unit Price\n"
    "2026-01-03,Chain Lube,CL-100,3,9.99\n"
    "2026-01-04,Inner Tube 700c,IT-700,10,5.50\n"
    "2026-01-05,Bar Tape,BT-200,2,12.00\n"
    "2026-01-06,Brake Pads,BP-300,4,15.25\n"
    "2026-01-07,Chain Lube,CL-100,1,9.99\n"
).encode()

_FULL_FIELD_MAPPING = {
    "sale_date": "Order Date",
    "product_name": "Item Description",
    "sku": "SKU",
    "quantity": "Qty",
    "unit_price": "Unit Price",
    "total_amount": None,
    "cost_price_at_sale": None,
    "order_reference": None,
}


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    # No real R2 in tests — same seam faked in test_uploads_service.py,
    # extended here to cover the new download path B7 adds.
    monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(_CSV_CONTENT))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: _CSV_CONTENT)


def _make_uploaded(db_session, business_id, filename="sales.csv"):
    repo = UploadRepository(db_session)
    upload = repo.create(
        business_id=business_id,
        storage_key=f"{business_id}/test/{filename}",
        original_filename=filename,
        uploaded_by="user-a",
        entity_type="sales",
    )
    return repo.set_status(upload, status="uploaded")


def test_detect_mapping_for_a_fresh_source_needs_confirmation(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)

    result = service.detect_mapping_for_upload(db_session, upload)

    assert result.status == "needs_confirmation"
    assert result.mapping_profile_id is None
    assert result.suggested_mapping["sale_date"] == "Order Date"
    assert result.suggested_mapping["unit_price"] == "Unit Price"


def test_detect_mapping_requires_the_upload_step_to_be_complete(db_session, business_id):
    upload = UploadRepository(db_session).create(
        business_id=business_id,
        storage_key="x",
        original_filename="sales.csv",
        uploaded_by="user-a",
        entity_type="sales",
    )  # still "pending" — never marked "uploaded"

    with pytest.raises(UploadNotReady):
        service.detect_mapping_for_upload(db_session, upload)


def test_confirm_mapping_persists_a_profile_and_creates_an_import_record(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)

    record, profile_id = service.confirm_mapping(db_session, upload, _FULL_FIELD_MAPPING)

    assert record.status == "mapped"
    assert record.upload_id == upload.id
    assert record.mapping_profile_id == profile_id

    signature = detection.compute_source_signature("sales", _HEADER)
    profile = ImportMappingProfileRepository(db_session).get_by_signature(business_id, signature)
    assert profile is not None
    assert profile.column_mapping["fields"] == _FULL_FIELD_MAPPING
    assert profile.column_mapping["entity_type"] == "sales"

    refreshed = UploadRepository(db_session).get_for_business(upload.id, business_id)
    assert refreshed.status == "mapped"


def test_second_upload_from_the_same_source_is_reused_with_zero_input(db_session, business_id):
    first = _make_uploaded(db_session, business_id, filename="a.csv")
    service.confirm_mapping(db_session, first, _FULL_FIELD_MAPPING)

    second = _make_uploaded(db_session, business_id, filename="b.csv")  # byte-identical headers
    result = service.detect_mapping_for_upload(db_session, second)

    assert result.status == "reused"
    assert result.mapping_profile_id is not None
    assert result.suggested_mapping == _FULL_FIELD_MAPPING

    # "Zero input" means fully processed, not left waiting for a
    # confirmation step the user will never be asked for.
    refreshed = UploadRepository(db_session).get_for_business(second.id, business_id)
    assert refreshed.status == "mapped"


def test_reconfirming_the_same_source_updates_rather_than_duplicates_the_profile(db_session, business_id):
    upload1 = _make_uploaded(db_session, business_id, filename="a.csv")
    service.confirm_mapping(db_session, upload1, _FULL_FIELD_MAPPING)

    corrected_mapping = dict(_FULL_FIELD_MAPPING, sku=None)  # user removes a wrong sku guess
    upload2 = _make_uploaded(db_session, business_id, filename="b.csv")
    service.confirm_mapping(db_session, upload2, corrected_mapping)

    profiles = db_session.scalars(
        select(ImportMappingProfile).where(ImportMappingProfile.business_id == business_id)
    ).all()
    assert len(profiles) == 1
    assert profiles[0].column_mapping["fields"]["sku"] is None


def test_confirm_mapping_rejects_a_mapping_missing_both_price_fields(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)
    field_mapping = dict(_FULL_FIELD_MAPPING, unit_price=None, total_amount=None)

    with pytest.raises(InsufficientMapping):
        service.confirm_mapping(db_session, upload, field_mapping)


def test_confirm_mapping_rejects_a_column_name_not_in_the_file(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)
    field_mapping = dict(_FULL_FIELD_MAPPING, sale_date="Not A Real Column")

    with pytest.raises(InvalidFieldMapping):
        service.confirm_mapping(db_session, upload, field_mapping)


def test_confirm_mapping_rejects_the_wrong_key_shape(db_session, business_id):
    upload = _make_uploaded(db_session, business_id)

    with pytest.raises(InvalidFieldMapping):
        service.confirm_mapping(db_session, upload, {"sale_date": "Order Date"})
