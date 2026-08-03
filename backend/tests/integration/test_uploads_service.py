import pytest

from app.imports import r2_client, service
from app.imports.exceptions import UnsupportedFileType
from app.repositories.upload import UploadRepository


@pytest.fixture(autouse=True)
def _fake_presigned_url(monkeypatch):
    # No real R2 credentials in tests — the SDK boundary is the seam to
    # fake, same as app/billing/client.py is faked in the billing tests.
    monkeypatch.setattr(
        r2_client, "generate_upload_url", lambda *, storage_key: f"https://r2.test/{storage_key}"
    )


def test_create_upload_rejects_an_unsupported_extension(db_session, business_id):
    with pytest.raises(UnsupportedFileType):
        service.create_upload(
            db_session, business_id=business_id, filename="sales.pdf", uploaded_by="user-a",
            entity_type="sales",
        )


def test_create_upload_rejects_a_missing_extension(db_session, business_id):
    with pytest.raises(UnsupportedFileType):
        service.create_upload(
            db_session, business_id=business_id, filename="sales", uploaded_by="user-a",
            entity_type="sales",
        )


def test_create_upload_persists_a_pending_row_and_returns_a_presigned_url(db_session, business_id):
    upload, upload_url = service.create_upload(
        db_session, business_id=business_id, filename="Sales Export.CSV", uploaded_by="user-a",
        entity_type="sales",
    )

    assert upload.status == "pending"
    assert upload.original_filename == "Sales Export.CSV"
    assert upload.entity_type == "sales"
    assert upload.business_id == business_id
    assert upload.storage_key.startswith(f"{business_id}/")
    assert upload.storage_key.endswith(".csv")
    assert upload_url == f"https://r2.test/{upload.storage_key}"


def test_mark_uploaded_sets_status_to_uploaded(db_session, business_id):
    upload, _ = service.create_upload(
        db_session, business_id=business_id, filename="sales.xlsx", uploaded_by="user-a",
        entity_type="sales",
    )

    updated = service.mark_uploaded(db_session, upload)

    assert updated.status == "uploaded"
    assert UploadRepository(db_session).get_for_business(upload.id, business_id).status == "uploaded"
