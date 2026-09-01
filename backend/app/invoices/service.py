"""Orchestrates the PDF supplier-invoice ingestion pipeline: upload ->
extraction -> review/correction -> confirm -> the real purchase ledger,
via app/imports/importer.py::write_purchases_batch (the SAME function
CSV purchases imports use) -> undo. Route handlers stay thin (CLAUDE.md);
this is where that logic lives, one level above the R2/PDF-parsing
boundaries (app/imports/r2_client.py, app/invoices/pdf_reader.py).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.application.alerts import refresh_low_stock_alerts
from app.application.notifications import notify_import_completed, resolve_data_freshness
from app.application.products import recalculate_thresholds_after_upload
from app.application.suppliers import ProductNotFound, SupplierNotFound
from app.imports import importer
from app.imports import r2_client
from app.invoices import duplicates as duplicates_module
from app.invoices import extraction
from app.invoices import pdf_reader
from app.invoices.exceptions import (
    CorruptPdf,
    DuplicateInvoiceExact,
    DuplicateInvoicePlausible,
    EncryptedPdf,
    InvoiceDraftNotReady,
    InvoiceFileTooLarge,
    InvoiceHasBlockingIssues,
    InvoiceRateLimitExceeded,
    InvoiceTooManyPages,
    NoExtractableText,
    UnsupportedInvoiceFileType,
)
from app.invoices.matching import (
    ProductMatcher,
    SupplierMatcher,
    default_resolution_action,
    resolve_product_for_line,
)
from app.models.invoice import LINE_RESOLUTION_ACTIONS, InvoiceDraft, InvoiceDraftLine
from app.repositories.audit_log import record_audit_event
from app.repositories.import_record import ImportRecordRepository
from app.repositories.invoice import InvoiceDraftLineRepository, InvoiceDraftRepository
from app.repositories.product import ProductRepository
from app.repositories.supplier import SupplierRepository
from app.repositories.upload import UploadRepository

logger = logging.getLogger(__name__)

# Parsing runs inline in the request, with no background job queue to
# throttle at (spec §5.5) — a simple per-business rolling-window cap,
# same lightweight counting shape as AIRequestRepository's daily cap.
_RATE_LIMIT_WINDOW = timedelta(hours=1)
_RATE_LIMIT_MAX_UPLOADS = 20

_EDITABLE_STATUSES = ("needs_review",)
_DISCARDABLE_STATUSES = ("needs_review", "failed")

_FAILURE_REASON_BY_EXCEPTION = {
    InvoiceTooManyPages: "oversized",
    EncryptedPdf: "encrypted",
    CorruptPdf: "corrupt",
    NoExtractableText: "no_extractable_text",
}


# --- Upload + extraction -------------------------------------------------


def create_invoice_draft(
    db: Session, *, business_id: uuid.UUID, uploaded_by: str, filename: str, file_bytes: bytes
) -> InvoiceDraft:
    window_start = datetime.now(timezone.utc) - _RATE_LIMIT_WINDOW
    if InvoiceDraftRepository(db).count_created_since(business_id, window_start) >= _RATE_LIMIT_MAX_UPLOADS:
        raise InvoiceRateLimitExceeded()

    # Cheap checks before any storage write — mirrors app/imports/
    # service.py::create_upload's own "reject before touching R2" order.
    if not filename.lower().endswith(".pdf"):
        raise UnsupportedInvoiceFileType()
    if len(file_bytes) > pdf_reader.MAX_FILE_SIZE_BYTES:
        raise InvoiceFileTooLarge(len(file_bytes), pdf_reader.MAX_FILE_SIZE_BYTES)

    file_hash = pdf_reader.compute_file_hash(file_bytes)
    storage_key = f"invoices/{business_id}/{uuid.uuid4()}.pdf"
    r2_client.put_object_bytes(storage_key=storage_key, data=file_bytes, content_type="application/pdf")

    draft = InvoiceDraftRepository(db).create(
        business_id=business_id,
        storage_key=storage_key,
        original_filename=filename,
        uploaded_by=uploaded_by,
        source_file_hash=file_hash,
    )
    _run_extraction(db, draft, file_bytes)
    return draft


def _mark_failed(draft_repo: InvoiceDraftRepository, draft: InvoiceDraft, *, failure_reason: str) -> InvoiceDraft:
    return draft_repo.update_extraction(
        draft,
        status="failed",
        failure_reason=failure_reason,
        extracted_at=datetime.now(timezone.utc),
        extracted_header=None,
        header_issue_codes=None,
        supplier_id=None,
        supplier_name_input=None,
        invoice_reference=None,
        invoice_date=None,
        due_date=None,
        currency=None,
        subtotal=None,
        tax_total=None,
        discount_total=None,
        shipping_total=None,
        grand_total=None,
        duplicate_status="none",
        duplicate_of_draft_id=None,
    )


def _run_extraction(db: Session, draft: InvoiceDraft, file_bytes: bytes) -> None:
    draft_repo = InvoiceDraftRepository(db)
    try:
        pdf = pdf_reader.read_pdf(file_bytes)
    except (InvoiceFileTooLarge, UnsupportedInvoiceFileType, InvoiceTooManyPages, EncryptedPdf, CorruptPdf, NoExtractableText) as exc:
        reason = _FAILURE_REASON_BY_EXCEPTION.get(type(exc), "unsupported_file_type")
        # Never log the file bytes/extracted content (spec §5.4) — only
        # the draft id and the machine-readable reason.
        logger.warning("Invoice draft %s failed extraction: %s", draft.id, reason)
        _mark_failed(draft_repo, draft, failure_reason=reason)
        return

    extracted = extraction.extract_invoice(pdf)
    _persist_extraction(db, draft, extracted)


def _persist_extraction(db: Session, draft: InvoiceDraft, extracted: extraction.ExtractedInvoice) -> None:
    business_id = draft.business_id
    draft_repo = InvoiceDraftRepository(db)
    line_repo = InvoiceDraftLineRepository(db)
    supplier_repo = SupplierRepository(db)

    supplier_matcher = SupplierMatcher(supplier_repo.list_for_business(business_id))
    supplier_id = None
    supplier_name_value = extracted.supplier_name.value
    if supplier_name_value:
        matched_supplier = supplier_matcher.resolve(supplier_name_value)
        if matched_supplier is not None:
            supplier_id = matched_supplier.id

    invoice_reference = extracted.invoice_reference.value
    invoice_date_value = extracted.invoice_date.value
    due_date_value = extracted.due_date.value
    currency = extracted.currency.value
    subtotal = extracted.subtotal.value
    tax_total = extracted.tax_total.value
    discount_total = extracted.discount_total.value
    shipping_total = extracted.shipping_total.value
    grand_total = extracted.grand_total.value

    dup = duplicates_module.check_duplicates(
        draft_repo,
        business_id=business_id,
        source_file_hash=draft.source_file_hash,
        supplier_id=supplier_id,
        invoice_reference=invoice_reference,
        invoice_date=invoice_date_value,
        currency=currency,
        grand_total=grand_total,
        exclude_draft_id=draft.id,
    )

    extracted_header_json = {
        field: getattr(extracted, field).to_json()
        for field in (
            "supplier_name", "invoice_reference", "invoice_date", "due_date", "currency",
            "subtotal", "tax_total", "discount_total", "shipping_total", "grand_total",
        )
    }

    draft = draft_repo.update_extraction(
        draft,
        status="needs_review",
        failure_reason=None,
        extracted_at=datetime.now(timezone.utc),
        extracted_header=extracted_header_json,
        header_issue_codes=extracted.header_issue_codes or None,
        supplier_id=supplier_id,
        supplier_name_input=supplier_name_value,
        invoice_reference=invoice_reference,
        invoice_date=invoice_date_value,
        due_date=due_date_value,
        currency=currency,
        subtotal=subtotal,
        tax_total=tax_total,
        discount_total=discount_total,
        shipping_total=shipping_total,
        grand_total=grand_total,
        duplicate_status=dup.status,
        duplicate_of_draft_id=dup.duplicate_of_draft_id,
    )

    product_matcher = ProductMatcher(ProductRepository(db).list_for_business(business_id))
    for line in extracted.lines:
        match = resolve_product_for_line(
            supplier_repo=supplier_repo,
            business_id=business_id,
            supplier_id=supplier_id,
            supplier_sku=line.supplier_sku.value,
            description=line.description.value,
            product_matcher=product_matcher,
        )
        resolution_action = default_resolution_action(match)
        line_repo.create(
            business_id=business_id,
            invoice_draft_id=draft.id,
            line_number=line.line_number,
            extracted_fields={
                field: getattr(line, field).to_json()
                for field in (
                    "description", "supplier_sku", "quantity", "unit", "unit_price",
                    "line_total", "tax_rate", "tax_amount", "discount_amount",
                )
            },
            description=line.description.value,
            supplier_sku=line.supplier_sku.value,
            quantity=line.quantity.value,
            unit=line.unit.value,
            unit_price=line.unit_price.value,
            line_total=line.line_total.value,
            tax_rate=line.tax_rate.value,
            tax_amount=line.tax_amount.value,
            discount_amount=line.discount_amount.value,
            resolution_action=resolution_action,
            matched_product_id=match.product_id if match.action == "existing" else None,
            proposed_name=match.create_name if match.action == "create" else None,
            proposed_sku=match.create_sku if match.action == "create" else None,
            issue_code=line.issue_code,
        )
    db.commit()


# --- Reads -----------------------------------------------------------------


def list_invoice_drafts(db: Session, business_id: uuid.UUID) -> list[InvoiceDraft]:
    return InvoiceDraftRepository(db).list_for_business(business_id)


def list_invoice_draft_lines(db: Session, draft: InvoiceDraft) -> list[InvoiceDraftLine]:
    return InvoiceDraftLineRepository(db).list_for_draft(draft.business_id, draft.id)


# --- Review / correction ---------------------------------------------------


def update_invoice_draft_header(db: Session, draft: InvoiceDraft, fields: dict) -> InvoiceDraft:
    if draft.status not in _EDITABLE_STATUSES:
        raise InvoiceDraftNotReady(draft.status)
    if "supplier_id" in fields and fields["supplier_id"] is not None:
        supplier = SupplierRepository(db).get_for_business(draft.business_id, fields["supplier_id"])
        if supplier is None:
            raise SupplierNotFound(str(fields["supplier_id"]))
    draft = InvoiceDraftRepository(db).update_header_fields(draft, **fields)
    _recompute_header_issues(db, draft)
    return draft


def update_invoice_draft_line(
    db: Session, draft: InvoiceDraft, line: InvoiceDraftLine, fields: dict
) -> InvoiceDraftLine:
    if draft.status not in _EDITABLE_STATUSES:
        raise InvoiceDraftNotReady(draft.status)
    if "resolution_action" in fields and fields["resolution_action"] not in LINE_RESOLUTION_ACTIONS:
        raise ValueError(f"Invalid resolution_action: {fields['resolution_action']!r}")
    if fields.get("matched_product_id") is not None:
        product = ProductRepository(db).get_for_business(draft.business_id, fields["matched_product_id"])
        if product is None:
            raise ProductNotFound(str(fields["matched_product_id"]))

    line = InvoiceDraftLineRepository(db).update_fields(line, **fields)
    issue_code = extraction.compute_line_issue_code(
        description=line.description, quantity=line.quantity, unit_price=line.unit_price, line_total=line.line_total
    )
    line = InvoiceDraftLineRepository(db).update_fields(line, issue_code=issue_code)
    _recompute_header_issues(db, draft)
    return line


def _recompute_header_issues(db: Session, draft: InvoiceDraft) -> None:
    lines = InvoiceDraftLineRepository(db).list_for_draft(draft.business_id, draft.id)
    non_excluded = [ln for ln in lines if ln.resolution_action != "excluded"]
    issues = extraction.compute_header_issue_codes(
        subtotal=draft.subtotal,
        tax_total=draft.tax_total,
        discount_total=draft.discount_total,
        shipping_total=draft.shipping_total,
        grand_total=draft.grand_total,
        line_signatures=[(ln.description, ln.quantity, ln.unit_price) for ln in non_excluded],
        line_totals=[ln.line_total for ln in non_excluded if ln.line_total is not None],
        line_count=len(non_excluded),
    )
    dup = duplicates_module.check_duplicates(
        InvoiceDraftRepository(db),
        business_id=draft.business_id,
        source_file_hash=draft.source_file_hash,
        supplier_id=draft.supplier_id,
        invoice_reference=draft.invoice_reference,
        invoice_date=draft.invoice_date,
        currency=draft.currency,
        grand_total=draft.grand_total,
        exclude_draft_id=draft.id,
    )
    InvoiceDraftRepository(db).update_header_fields(
        draft,
        header_issue_codes=issues or None,
        duplicate_status=dup.status,
        duplicate_of_draft_id=dup.duplicate_of_draft_id,
    )


# --- Confirm / undo / discard -----------------------------------------------


def _line_blocks_confirm(line: InvoiceDraftLine) -> bool:
    if line.resolution_action == "excluded":
        return False
    if line.resolution_action == "unresolved":
        return True
    if line.resolution_action == "match_existing":
        blocked = line.matched_product_id is None
    elif line.resolution_action == "create_new":
        blocked = not (line.proposed_name or line.proposed_sku)
    else:
        return True  # unrecognised value -- fail closed
    if blocked:
        return True
    if line.quantity is None or line.quantity <= 0:
        return True
    if line.quantity != line.quantity.to_integral_value():
        return True
    return False


def _blocking_line_ids(lines: list[InvoiceDraftLine]) -> list[uuid.UUID]:
    return [ln.id for ln in lines if _line_blocks_confirm(ln)]


@dataclass(frozen=True)
class ConfirmPreview:
    products_to_create: int
    products_to_match: int
    lines_excluded: int
    supplier_action: str
    supplier_name: str | None
    purchase_movement_count: int
    invoice_date: date | None
    blocking_issue_count: int
    duplicate_status: str


def _resolve_supplier_preview(db: Session, draft: InvoiceDraft) -> tuple[str, str | None]:
    if draft.supplier_id is not None:
        supplier = SupplierRepository(db).get_for_business(draft.business_id, draft.supplier_id)
        return "match_existing", (supplier.name if supplier else None)
    if draft.supplier_name_input:
        return "create_new", draft.supplier_name_input
    return "unknown", None


def preview_invoice_confirm(db: Session, draft: InvoiceDraft) -> ConfirmPreview:
    lines = InvoiceDraftLineRepository(db).list_for_draft(draft.business_id, draft.id)
    blocking_ids = _blocking_line_ids(lines)
    header_blocks = draft.invoice_date is None
    non_excluded = [ln for ln in lines if ln.resolution_action != "excluded"]

    supplier_action, supplier_name = _resolve_supplier_preview(db, draft)

    dup = duplicates_module.check_duplicates(
        InvoiceDraftRepository(db),
        business_id=draft.business_id,
        source_file_hash=draft.source_file_hash,
        supplier_id=draft.supplier_id,
        invoice_reference=draft.invoice_reference,
        invoice_date=draft.invoice_date,
        currency=draft.currency,
        grand_total=draft.grand_total,
        exclude_draft_id=draft.id,
    )

    return ConfirmPreview(
        products_to_create=sum(1 for ln in non_excluded if ln.resolution_action == "create_new"),
        products_to_match=sum(1 for ln in non_excluded if ln.resolution_action == "match_existing"),
        lines_excluded=len(lines) - len(non_excluded),
        supplier_action=supplier_action,
        supplier_name=supplier_name,
        purchase_movement_count=len(non_excluded),
        invoice_date=draft.invoice_date,
        blocking_issue_count=len(blocking_ids) + (1 if header_blocks else 0),
        duplicate_status=dup.status,
    )


@dataclass(frozen=True)
class ConfirmResult:
    import_record_id: uuid.UUID
    rows_imported: int
    rows_rejected: int
    rejection_summary: dict | None
    preview: ConfirmPreview


def confirm_invoice_import(
    db: Session, draft: InvoiceDraft, *, confirming_user_id: str, override_duplicate_warning: bool = False
) -> tuple[InvoiceDraft, ConfirmResult]:
    if draft.status not in _EDITABLE_STATUSES:
        raise InvoiceDraftNotReady(draft.status)

    lines = InvoiceDraftLineRepository(db).list_for_draft(draft.business_id, draft.id)
    blocking_ids = _blocking_line_ids(lines)
    if blocking_ids or draft.invoice_date is None:
        raise InvoiceHasBlockingIssues(blocking_ids)

    dup = duplicates_module.check_duplicates(
        InvoiceDraftRepository(db),
        business_id=draft.business_id,
        source_file_hash=draft.source_file_hash,
        supplier_id=draft.supplier_id,
        invoice_reference=draft.invoice_reference,
        invoice_date=draft.invoice_date,
        currency=draft.currency,
        grand_total=draft.grand_total,
        exclude_draft_id=draft.id,
    )
    if dup.status == "exact":
        raise DuplicateInvoiceExact(dup.duplicate_of_draft_id)
    if dup.status == "plausible" and not override_duplicate_warning:
        raise DuplicateInvoicePlausible(dup.duplicate_of_draft_id)

    preview = preview_invoice_confirm(db, draft)

    supplier_repo = SupplierRepository(db)
    supplier_name_for_rows: str | None = None
    if draft.supplier_id is not None:
        supplier = supplier_repo.get_for_business(draft.business_id, draft.supplier_id)
        supplier_name_for_rows = supplier.name if supplier else None
    elif draft.supplier_name_input:
        supplier_name_for_rows = draft.supplier_name_input

    matched_ids = {ln.matched_product_id for ln in lines if ln.matched_product_id is not None}
    products_by_id = {
        p.id: p for p in ProductRepository(db).list_for_business(draft.business_id) if p.id in matched_ids
    }

    parsed_rows: list[importer.ParsedPurchaseRow] = []
    for ln in lines:
        if ln.resolution_action == "excluded":
            continue
        if ln.resolution_action == "match_existing":
            product = products_by_id.get(ln.matched_product_id)
            # Re-resolved by name/SKU inside write_purchases_batch's own
            # fresh ProductMatcher — using the PRODUCT's own stored
            # name/sku (not the raw extracted description) guarantees
            # that re-match hits exactly this product, not a fuzzy guess.
            product_name = product.name if product else ln.description
            sku = product.sku if product else None
        else:  # create_new — validated non-blocking above, so at least
            # one of these is set.
            product_name = ln.proposed_name or ln.description
            sku = ln.proposed_sku
        parsed_rows.append(
            importer.ParsedPurchaseRow(
                row_number=ln.line_number,
                purchase_date=draft.invoice_date,
                product_name=product_name,
                sku=sku,
                quantity_received=int(ln.quantity),
                unit_cost=ln.unit_price,
                reference=draft.invoice_reference,
                category=None,
                supplier_name=supplier_name_for_rows,
            )
        )

    upload = UploadRepository(db).create(
        business_id=draft.business_id,
        storage_key=f"invoice-draft:{draft.id}",
        original_filename=f"Invoice: {draft.original_filename}",
        uploaded_by=confirming_user_id,
        entity_type="purchases",
    )
    UploadRepository(db).set_status(upload, status="mapped")
    import_record = ImportRecordRepository(db).create(
        business_id=draft.business_id,
        upload_id=upload.id,
        mapping_profile_id=None,
        entity_type="purchases",
        status="mapped",
    )

    rows_imported, warnings, touched_product_ids, duplicate_rejections = importer.write_purchases_batch(
        db, upload, import_record, parsed_rows
    )
    rejection_summary = importer.build_rejection_summary(duplicate_rejections, warnings)
    rows_total = rows_imported + len(duplicate_rejections)

    ImportRecordRepository(db).update_after_import(
        import_record,
        status="completed",
        rows_total=rows_total,
        rows_imported=rows_imported,
        rows_rejected=len(duplicate_rejections),
        rejection_summary=rejection_summary,
    )
    UploadRepository(db).set_status_flush_only(upload, status="imported")
    db.commit()

    # Retention: unlike a CSV Upload (ADR-008 deletes right after import
    # too), this mirrors that same default rather than diverging from it
    # — see docs/governance/11_Development_Roadmap.md's changelog entry
    # for the reasoning. The structured InvoiceDraft/InvoiceDraftLine
    # rows (never deleted) remain the durable trace-back record (spec
    # §6), not the raw PDF bytes.
    try:
        r2_client.delete_object(storage_key=draft.storage_key)
    except Exception:
        logger.exception("Failed to delete R2 object after confirmed invoice import: %s", draft.id)

    draft = InvoiceDraftRepository(db).mark_confirmed(draft, import_record_id=import_record.id)

    try:
        refresh_low_stock_alerts(db, business_id=draft.business_id, product_ids=touched_product_ids)
    except Exception:
        logger.exception("Failed to refresh low-stock alerts after invoice import for business: %s", draft.business_id)
    try:
        recalculate_thresholds_after_upload(
            db, business_id=draft.business_id, product_ids=touched_product_ids, triggered_by_user_id=confirming_user_id
        )
    except Exception:
        logger.exception("Failed to recalculate thresholds after invoice import for business: %s", draft.business_id)
    try:
        notify_import_completed(
            db,
            business_id=draft.business_id,
            import_record_id=import_record.id,
            entity_type="purchases",
            rows_imported=rows_imported,
            rows_rejected=len(duplicate_rejections),
        )
        resolve_data_freshness(db, business_id=draft.business_id, entity_type="purchases")
        db.commit()
    except Exception:
        logger.exception("Failed to create import-completed notification for business: %s", draft.business_id)

    # Field names only, never values (app/repositories/audit_log.py's own rule).
    record_audit_event(
        db,
        business_id=draft.business_id,
        user_id=confirming_user_id,
        action="invoice_import_confirmed",
        target_type="invoice_draft",
        target_id=str(draft.id),
        metadata={"import_record_id": str(import_record.id), "rows_imported": rows_imported},
    )
    db.commit()

    return draft, ConfirmResult(
        import_record_id=import_record.id,
        rows_imported=rows_imported,
        rows_rejected=len(duplicate_rejections),
        rejection_summary=rejection_summary,
        preview=preview,
    )


def undo_invoice_import(db: Session, draft: InvoiceDraft, *, user_id: str) -> InvoiceDraft:
    if draft.status != "confirmed" or draft.import_record_id is None:
        raise InvoiceDraftNotReady(draft.status)
    import_record = ImportRecordRepository(db).get_for_business(draft.import_record_id, draft.business_id)
    if import_record is None:
        raise InvoiceDraftNotReady(draft.status)

    record = importer.undo_import(db, import_record)  # raises ImportNotReversible if already reversed
    draft = InvoiceDraftRepository(db).mark_reversed(draft, reversed_at=record.reversed_at or datetime.now(timezone.utc))
    record_audit_event(
        db, business_id=draft.business_id, user_id=user_id, action="invoice_import_undone",
        target_type="invoice_draft", target_id=str(draft.id),
        metadata={"import_record_id": str(import_record.id)},
    )
    db.commit()
    return draft


def discard_invoice_draft(db: Session, draft: InvoiceDraft, *, user_id: str) -> None:
    if draft.status not in _DISCARDABLE_STATUSES:
        raise InvoiceDraftNotReady(draft.status)
    try:
        r2_client.delete_object(storage_key=draft.storage_key)
    except Exception:
        logger.exception("Failed to delete R2 object for discarded invoice draft: %s", draft.id)
    record_audit_event(
        db, business_id=draft.business_id, user_id=user_id, action="invoice_draft_discarded",
        target_type="invoice_draft", target_id=str(draft.id),
    )
    InvoiceDraftLineRepository(db).delete_for_draft(draft.business_id, draft.id)
    InvoiceDraftRepository(db).delete(draft)
