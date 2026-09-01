"""Covers app/invoices/service.py's orchestration against a real (SQLite)
DB — extraction persistence, review corrections, confirm (including
blocking issues and duplicate detection), undo, and discard. R2 is
monkeypatched to an in-memory dict (same style as tests/integration/
test_business_logo_api.py). The underlying purchases write path
(write_purchases_batch) and undo (importer.undo_import) are the SAME,
already-tested functions CSV purchases imports use — these tests focus
on what's actually new here: extraction persistence, the review/
correction API, and duplicate detection, not re-proving product/supplier
matching that app/imports/ already covers.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.imports import r2_client
from app.invoices import service
from app.invoices.exceptions import (
    DuplicateInvoiceExact,
    DuplicateInvoicePlausible,
    InvoiceDraftNotReady,
    InvoiceHasBlockingIssues,
    InvoiceRateLimitExceeded,
)
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.supplier import Supplier
from app.repositories.invoice import InvoiceDraftLineRepository, InvoiceDraftRepository
from tests.invoice_pdf_helpers import build_encrypted_pdf, build_invoice_pdf, build_no_table_pdf


@pytest.fixture(autouse=True)
def _fake_r2(monkeypatch):
    store: dict[str, bytes] = {}

    def _put(*, storage_key, data, content_type):
        store[storage_key] = data

    def _download(*, storage_key):
        return store[storage_key]

    def _delete(*, storage_key):
        store.pop(storage_key, None)

    monkeypatch.setattr(r2_client, "put_object_bytes", _put)
    monkeypatch.setattr(r2_client, "download_object", _download)
    monkeypatch.setattr(r2_client, "delete_object", _delete)
    return store


def _upload(db_session, business_id, *, file_bytes=None, uploaded_by="user-1") -> "InvoiceDraft":
    return service.create_invoice_draft(
        db_session, business_id=business_id, uploaded_by=uploaded_by, filename="invoice.pdf",
        file_bytes=file_bytes if file_bytes is not None else build_invoice_pdf(),
    )


# --- Upload + extraction ----------------------------------------------------


def test_a_clean_invoice_is_extracted_into_needs_review_with_typed_lines(db_session, business_id):
    draft = _upload(db_session, business_id)

    assert draft.status == "needs_review"
    assert draft.failure_reason is None
    assert draft.invoice_reference == "INV-2024-0456"
    assert draft.invoice_date == date(2026, 3, 15)
    assert draft.grand_total == Decimal("270.60")

    lines = InvoiceDraftLineRepository(db_session).list_for_draft(business_id, draft.id)
    assert len(lines) == 2
    assert lines[0].description == "Road Tyre 700x25c"
    assert lines[0].resolution_action == "unresolved"  # no existing product yet -- never auto-matched to nothing


def test_a_line_matching_an_existing_products_sku_defaults_to_match_existing(db_session, business_id):
    product = Product(business_id=business_id, sku="TYR-001", name="Road Tyre 700x25c", cost_price=Decimal("10"), sell_price=Decimal("20"))
    db_session.add(product)
    db_session.commit()

    draft = _upload(db_session, business_id)

    lines = InvoiceDraftLineRepository(db_session).list_for_draft(business_id, draft.id)
    tyre_line = next(ln for ln in lines if ln.supplier_sku == "TYR-001")
    assert tyre_line.resolution_action == "match_existing"
    assert tyre_line.matched_product_id == product.id


def test_a_line_with_no_identifier_match_proposes_create_new_but_stays_unresolved(db_session, business_id):
    draft = _upload(db_session, business_id)

    lines = InvoiceDraftLineRepository(db_session).list_for_draft(business_id, draft.id)
    assert all(ln.resolution_action == "unresolved" for ln in lines)
    assert all(ln.proposed_name for ln in lines)  # a starting proposal exists, just not auto-applied


def test_supplier_matching_an_existing_supplier_by_name_is_auto_resolved(db_session, business_id):
    supplier = Supplier(business_id=business_id, name="Acme Bike Parts Ltd", normalized_name="acme bike parts ltd")
    db_session.add(supplier)
    db_session.commit()

    draft = _upload(db_session, business_id)

    assert draft.supplier_id == supplier.id


def test_an_encrypted_pdf_produces_a_failed_draft_with_a_machine_readable_reason(db_session, business_id):
    draft = _upload(db_session, business_id, file_bytes=build_encrypted_pdf())

    assert draft.status == "failed"
    assert draft.failure_reason == "encrypted"


def test_a_pdf_with_no_detected_line_items_still_reaches_review_with_an_issue_code(db_session, business_id):
    draft = _upload(db_session, business_id, file_bytes=build_no_table_pdf())

    assert draft.status == "needs_review"
    assert "line_items_not_detected" in (draft.header_issue_codes or [])
    assert InvoiceDraftLineRepository(db_session).list_for_draft(business_id, draft.id) == []


def test_upload_rate_limit_blocks_further_uploads_within_the_window(db_session, business_id, monkeypatch):
    monkeypatch.setattr(service, "_RATE_LIMIT_MAX_UPLOADS", 2)
    _upload(db_session, business_id)
    _upload(db_session, business_id)

    with pytest.raises(InvoiceRateLimitExceeded):
        _upload(db_session, business_id)


# --- Review / correction ----------------------------------------------------


def test_updating_the_header_recomputes_duplicate_and_arithmetic_state(db_session, business_id):
    draft = _upload(db_session, business_id)

    draft = service.update_invoice_draft_header(db_session, draft, {"grand_total": Decimal("999.99")})

    assert draft.grand_total == Decimal("999.99")
    assert "grand_total_mismatch" in (draft.header_issue_codes or [])


def test_updating_a_line_to_excluded_removes_it_from_the_blocking_and_arithmetic_checks(db_session, business_id):
    draft = _upload(db_session, business_id)
    lines = InvoiceDraftLineRepository(db_session).list_for_draft(business_id, draft.id)

    service.update_invoice_draft_line(db_session, draft, lines[0], {"resolution_action": "excluded"})
    service.update_invoice_draft_line(
        db_session, draft, lines[1],
        {"resolution_action": "create_new", "proposed_name": "Inner Tube 700c"},
    )

    preview = service.preview_invoice_confirm(db_session, draft)
    assert preview.lines_excluded == 1
    assert preview.blocking_issue_count == 0


def test_an_invalid_resolution_action_is_rejected(db_session, business_id):
    draft = _upload(db_session, business_id)
    lines = InvoiceDraftLineRepository(db_session).list_for_draft(business_id, draft.id)

    with pytest.raises(ValueError):
        service.update_invoice_draft_line(db_session, draft, lines[0], {"resolution_action": "not_a_real_action"})


def test_editing_a_confirmed_draft_is_rejected(db_session, business_id):
    draft = _upload(db_session, business_id)
    lines = InvoiceDraftLineRepository(db_session).list_for_draft(business_id, draft.id)
    for ln in lines:
        service.update_invoice_draft_line(
            db_session, draft, ln, {"resolution_action": "create_new", "proposed_name": ln.description}
        )
    draft, _ = service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")

    with pytest.raises(InvoiceDraftNotReady):
        service.update_invoice_draft_header(db_session, draft, {"invoice_reference": "X"})


# --- Confirm -----------------------------------------------------------------


def _resolve_all_lines_as_new_products(db_session, draft):
    lines = InvoiceDraftLineRepository(db_session).list_for_draft(draft.business_id, draft.id)
    for ln in lines:
        service.update_invoice_draft_line(
            db_session, draft, ln, {"resolution_action": "create_new", "proposed_name": ln.description or "Line item"}
        )
    return InvoiceDraftRepository(db_session).get_for_business(draft.id, draft.business_id)


def test_confirm_blocks_while_a_line_is_unresolved(db_session, business_id):
    draft = _upload(db_session, business_id)

    with pytest.raises(InvoiceHasBlockingIssues):
        service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")


def test_confirm_writes_through_the_same_purchases_ledger_and_deletes_the_r2_object(db_session, business_id, _fake_r2):
    draft = _upload(db_session, business_id)
    draft = _resolve_all_lines_as_new_products(db_session, draft)
    assert draft.storage_key in _fake_r2

    draft, result = service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")

    assert draft.status == "confirmed"
    assert result.rows_imported == 2
    assert draft.storage_key not in _fake_r2  # retention: deleted right after a successful confirm

    products = db_session.query(Product).filter(Product.business_id == business_id).all()
    assert len(products) == 2
    movements = db_session.query(InventoryMovement).filter(InventoryMovement.business_id == business_id).all()
    assert len(movements) == 2
    assert all(m.reason == "purchase" for m in movements)
    assert all(m.import_record_id == draft.import_record_id for m in movements)


def test_confirm_matches_an_existing_supplier_by_name_when_none_was_extracted(db_session, business_id):
    supplier = Supplier(business_id=business_id, name="Acme Bike Parts Ltd", normalized_name="acme bike parts ltd")
    db_session.add(supplier)
    db_session.commit()

    draft = _upload(db_session, business_id)  # auto-matches the supplier by name during extraction
    draft = _resolve_all_lines_as_new_products(db_session, draft)

    draft, _ = service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")

    movements = db_session.query(InventoryMovement).filter(InventoryMovement.business_id == business_id).all()
    assert all(m.supplier_id == supplier.id for m in movements)


def test_confirm_leaves_unknown_supplier_when_the_user_clears_it(db_session, business_id):
    # "Unknown supplier" stays valid even for an invoice import — a
    # supplier must never become mandatory solely because an invoice was
    # uploaded (spec, "Existing behaviour to preserve"). Explicitly
    # cleared via a header correction rather than relying on extraction
    # finding nothing at all (its own low-confidence fallback can still
    # propose *something* worth showing the user, by design).
    draft = _upload(db_session, business_id)
    draft = service.update_invoice_draft_header(db_session, draft, {"supplier_id": None, "supplier_name_input": None})
    draft = _resolve_all_lines_as_new_products(db_session, draft)

    draft, _ = service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")

    movements = db_session.query(InventoryMovement).filter(InventoryMovement.business_id == business_id).all()
    assert all(m.supplier_id is None for m in movements)


def test_confirm_blocks_without_a_resolved_invoice_date(db_session, business_id):
    # invoice_date extraction fails entirely if the label text never
    # appears -- simulate by clearing it via a header correction.
    draft = _upload(db_session, business_id)
    draft = _resolve_all_lines_as_new_products(db_session, draft)
    service.update_invoice_draft_header(db_session, draft, {"invoice_date": None})
    draft = InvoiceDraftRepository(db_session).get_for_business(draft.id, business_id)

    with pytest.raises(InvoiceHasBlockingIssues):
        service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")


def test_confirming_an_exact_duplicate_by_file_hash_is_blocked(db_session, business_id):
    file_bytes = build_invoice_pdf()
    draft_a = _upload(db_session, business_id, file_bytes=file_bytes)
    draft_a = _resolve_all_lines_as_new_products(db_session, draft_a)
    service.confirm_invoice_import(db_session, draft_a, confirming_user_id="user-1")

    # Retry: same exact bytes uploaded again after the first was confirmed.
    draft_b = _upload(db_session, business_id, file_bytes=file_bytes)
    assert draft_b.duplicate_status == "exact"
    draft_b = _resolve_all_lines_as_new_products(db_session, draft_b)

    with pytest.raises(DuplicateInvoiceExact):
        service.confirm_invoice_import(db_session, draft_b, confirming_user_id="user-1")


def test_a_plausible_duplicate_requires_an_explicit_override_to_confirm(db_session, business_id):
    # Same date/currency/grand_total, but different file bytes and a
    # different reference -- not an exact match, only a plausible one.
    draft_a = _upload(db_session, business_id, file_bytes=build_invoice_pdf(invoice_reference="INV-A"))
    draft_a = _resolve_all_lines_as_new_products(db_session, draft_a)
    service.confirm_invoice_import(db_session, draft_a, confirming_user_id="user-1")

    draft_b = _upload(db_session, business_id, file_bytes=build_invoice_pdf(invoice_reference="INV-B"))
    assert draft_b.duplicate_status == "plausible"
    draft_b = _resolve_all_lines_as_new_products(db_session, draft_b)

    with pytest.raises(DuplicateInvoicePlausible):
        service.confirm_invoice_import(db_session, draft_b, confirming_user_id="user-1")

    # Explicit override proceeds.
    draft_b, result = service.confirm_invoice_import(
        db_session, draft_b, confirming_user_id="user-1", override_duplicate_warning=True
    )
    assert draft_b.status == "confirmed"


def test_a_failed_drafts_hash_does_not_block_a_later_real_upload_of_the_same_bytes(db_session, business_id):
    # A failed attempt's hash must not poison a genuine retry of the
    # identical bytes (spec §4: "Retry of a failed processing job must
    # not create duplicate drafts") -- a failed draft isn't a real
    # invoice yet. Exercised directly against app/invoices/duplicates.py
    # (the actual exclusion logic under test): create_invoice_draft never
    # runs a duplicate check for a failed extraction at all, so this
    # proves the exclusion itself, not just an incidental non-call.
    from app.invoices import duplicates as duplicates_module

    repo = InvoiceDraftRepository(db_session)
    failed_draft = repo.create(
        business_id=business_id, storage_key="x", original_filename="x.pdf", uploaded_by="user-1",
        source_file_hash="deadbeef",
    )
    repo.update_extraction(
        failed_draft, status="failed", failure_reason="encrypted", extracted_at=None, extracted_header=None,
        header_issue_codes=None, supplier_id=None, supplier_name_input=None, invoice_reference=None,
        invoice_date=None, due_date=None, currency=None, subtotal=None, tax_total=None, discount_total=None,
        shipping_total=None, grand_total=None, duplicate_status="none", duplicate_of_draft_id=None,
    )

    result = duplicates_module.check_duplicates(
        repo, business_id=business_id, source_file_hash="deadbeef", supplier_id=None, invoice_reference=None,
        invoice_date=None, currency=None, grand_total=None,
    )

    assert result.status == "none"


# --- Undo / discard ----------------------------------------------------------


def test_undo_reverses_the_movements_but_keeps_the_created_product_and_supplier(db_session, business_id):
    supplier = Supplier(business_id=business_id, name="Acme Bike Parts Ltd", normalized_name="acme bike parts ltd")
    db_session.add(supplier)
    db_session.commit()

    draft = _upload(db_session, business_id)
    draft = _resolve_all_lines_as_new_products(db_session, draft)
    draft, _ = service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")
    product_ids = [p.id for p in db_session.query(Product).filter(Product.business_id == business_id).all()]

    draft = service.undo_invoice_import(db_session, draft, user_id="user-1")

    assert draft.status == "reversed"
    movements = db_session.query(InventoryMovement).filter(InventoryMovement.business_id == business_id).all()
    assert movements == []
    surviving_products = db_session.query(Product).filter(Product.id.in_(product_ids)).all()
    assert len(surviving_products) == len(product_ids)  # never deleted by undo
    assert db_session.query(Supplier).filter(Supplier.id == supplier.id).one_or_none() is not None


def test_discard_removes_a_draft_still_under_review_and_its_r2_object(db_session, business_id, _fake_r2):
    draft = _upload(db_session, business_id)
    assert draft.storage_key in _fake_r2

    service.discard_invoice_draft(db_session, draft, user_id="user-1")

    assert draft.storage_key not in _fake_r2
    assert InvoiceDraftRepository(db_session).get_for_business(draft.id, business_id) is None


def test_discard_is_rejected_once_confirmed(db_session, business_id):
    draft = _upload(db_session, business_id)
    draft = _resolve_all_lines_as_new_products(db_session, draft)
    draft, _ = service.confirm_invoice_import(db_session, draft, confirming_user_id="user-1")

    with pytest.raises(InvoiceDraftNotReady):
        service.discard_invoice_draft(db_session, draft, user_id="user-1")
