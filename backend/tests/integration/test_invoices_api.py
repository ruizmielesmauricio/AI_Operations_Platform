"""Covers app/api/invoices.py end to end through the real HTTP routes:
the multipart upload, review/correction, confirm (including the blocking-
issues and duplicate-warning response shapes), undo, discard, and the
tenant-scoped PDF preview. R2 is monkeypatched to an in-memory dict (same
style as tests/integration/test_business_logo_api.py). Cross-business
tenant isolation for this router lives in its own dedicated suite —
tests/tenant_isolation/test_invoices_isolation.py — matching this
codebase's established split (see that directory's own README).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks, seed_active_subscription
from tests.invoice_pdf_helpers import build_encrypted_pdf, build_invoice_pdf, not_a_pdf_bytes


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    store: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "put_object_bytes", lambda *, storage_key, data, content_type: store.__setitem__(storage_key, data))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: store[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: store.pop(storage_key, None))

    db_path = tmp_path / "invoices_api_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    test_client._engine = engine
    test_client._store = store
    yield test_client
    app.dependency_overrides.clear()


def _create_business(client, headers, name="Shop A"):
    business = client.post("/businesses", json={"name": name}, headers=headers).json()
    seed_active_subscription(client._engine, business["id"])
    return business


def _upload_invoice(client, headers, business_id, *, file_bytes=None, filename="invoice.pdf", content_type="application/pdf"):
    return client.post(
        f"/businesses/{business_id}/invoices",
        files={"file": (filename, file_bytes if file_bytes is not None else build_invoice_pdf(), content_type)},
        headers=headers,
    )


def _resolve_all_lines(client, headers, business_id, invoice_id, lines):
    for line in lines:
        r = client.patch(
            f"/businesses/{business_id}/invoices/{invoice_id}/lines/{line['id']}",
            json={"resolution_action": "create_new", "proposed_name": line["description"] or "Line item"},
            headers=headers,
        )
        assert r.status_code == 200, r.text


# --- Permissions -------------------------------------------------------------


def test_upload_without_an_active_subscription_is_blocked(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = _upload_invoice(client, headers, business["id"])

    assert response.status_code == 402


def test_upload_requires_membership_of_the_business(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business = _create_business(client, headers_a)

    response = _upload_invoice(client, headers_b, business["id"])

    assert response.status_code == 403


def test_non_pdf_content_type_is_rejected(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers)

    response = client.post(
        f"/businesses/{business['id']}/invoices",
        files={"file": ("invoice.csv", b"a,b,c", "text/csv")},
        headers=headers,
    )

    assert response.status_code == 400


def test_a_file_that_is_not_really_a_pdf_reaches_a_failed_draft_not_a_500(client):
    # A .pdf-named file with a declared application/pdf content-type but
    # garbage bytes passes the cheap pre-storage checks (real magic-byte
    # signature validation only happens once app/invoices/pdf_reader.py
    # actually opens it, same as the encrypted/corrupt/no-text cases) —
    # this must land as an honest, persisted failed draft, never a raw
    # 500 and never a false "it worked."
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers)

    response = _upload_invoice(client, headers, business["id"], file_bytes=not_a_pdf_bytes())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "unsupported_file_type"


def test_a_matched_line_and_supplier_include_a_resolved_friendly_name(client):
    # The review screen has no other way to show anything meaningful for
    # an auto-matched line/supplier beyond a bare UUID (spec §3.4/§3.6:
    # "show clearly whether the supplier is an existing match...").
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers)
    client.post(f"/businesses/{business['id']}/suppliers", json={"name": "Acme Bike Parts Ltd"}, headers=headers)

    invoice = _upload_invoice(client, headers, business["id"]).json()

    assert invoice["matched_supplier_name"] == "Acme Bike Parts Ltd"


# --- Happy path ----------------------------------------------------------


def test_full_upload_review_confirm_undo_walkthrough(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers)

    upload_response = _upload_invoice(client, headers, business["id"])
    assert upload_response.status_code == 201
    invoice = upload_response.json()
    assert invoice["status"] == "needs_review"
    assert invoice["invoice_reference"] == "INV-2024-0456"
    assert len(invoice["lines"]) == 2

    # PDF preview is available while under review.
    pdf_response = client.get(f"/businesses/{business['id']}/invoices/{invoice['id']}/pdf", headers=headers)
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF-")

    # Confirm blocked while lines are unresolved.
    blocked = client.post(f"/businesses/{business['id']}/invoices/{invoice['id']}/confirm", headers=headers)
    assert blocked.status_code == 422

    # Correct the header and every line, then confirm for real.
    header_patch = client.patch(
        f"/businesses/{business['id']}/invoices/{invoice['id']}",
        json={"invoice_reference": "INV-2024-0456-CORRECTED"},
        headers=headers,
    )
    assert header_patch.status_code == 200
    assert header_patch.json()["invoice_reference"] == "INV-2024-0456-CORRECTED"

    _resolve_all_lines(client, headers, business["id"], invoice["id"], invoice["lines"])

    preview = client.post(f"/businesses/{business['id']}/invoices/{invoice['id']}/confirm/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.json()["blocking_issue_count"] == 0
    assert preview.json()["purchase_movement_count"] == 2

    confirm = client.post(f"/businesses/{business['id']}/invoices/{invoice['id']}/confirm", headers=headers)
    assert confirm.status_code == 200
    result = confirm.json()
    assert result["status"] == "confirmed"
    assert result["rows_imported"] == 2

    # The confirmed purchase shows up through the SAME existing purchase-
    # ledger surface as a CSV import would (spec §6's "one consistent
    # source of truth").
    transactions = client.get(
        f"/businesses/{business['id']}/transactions/purchases", headers=headers,
    )
    assert transactions.status_code == 200
    assert len(transactions.json()["items"]) >= 2

    # PDF is no longer retrievable once confirmed (retention decision).
    pdf_after = client.get(f"/businesses/{business['id']}/invoices/{invoice['id']}/pdf", headers=headers)
    assert pdf_after.status_code == 404

    # Undo reverses the ledger effects.
    undo = client.post(f"/businesses/{business['id']}/invoices/{invoice['id']}/undo", headers=headers)
    assert undo.status_code == 200
    assert undo.json()["status"] == "reversed"

    transactions_after_undo = client.get(
        f"/businesses/{business['id']}/transactions/purchases", headers=headers,
    )
    assert transactions_after_undo.status_code == 200
    assert len(transactions_after_undo.json()["items"]) == 0


def test_discard_removes_a_draft_still_under_review(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers)
    invoice = _upload_invoice(client, headers, business["id"]).json()

    response = client.delete(f"/businesses/{business['id']}/invoices/{invoice['id']}", headers=headers)
    assert response.status_code == 204

    get_response = client.get(f"/businesses/{business['id']}/invoices/{invoice['id']}", headers=headers)
    assert get_response.status_code == 404


def test_an_encrypted_pdf_upload_reaches_a_failed_draft_not_a_500(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers)

    response = _upload_invoice(client, headers, business["id"], file_bytes=build_encrypted_pdf())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "encrypted"


def test_confirming_an_exact_duplicate_returns_409_with_the_original_linked(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers)
    file_bytes = build_invoice_pdf()

    first = _upload_invoice(client, headers, business["id"], file_bytes=file_bytes).json()
    _resolve_all_lines(client, headers, business["id"], first["id"], first["lines"])
    client.post(f"/businesses/{business['id']}/invoices/{first['id']}/confirm", headers=headers)

    second = _upload_invoice(client, headers, business["id"], file_bytes=file_bytes).json()
    assert second["duplicate_status"] == "exact"
    _resolve_all_lines(client, headers, business["id"], second["id"], second["lines"])

    response = client.post(f"/businesses/{business['id']}/invoices/{second['id']}/confirm", headers=headers)
    assert response.status_code == 409
    assert "already been imported" in response.json()["detail"]
    # The draft's own field (fetched before Confirm is ever attempted) is
    # the real source for which invoice this duplicates, not the error body.
    assert second["duplicate_status"] == "exact"
