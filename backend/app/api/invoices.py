import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.suppliers import ProductNotFound, SupplierNotFound
from app.billing.access import require_active_subscription
from app.imports import r2_client
from app.imports.exceptions import ImportNotReversible
from app.invoices import service
from app.invoices.exceptions import (
    DuplicateInvoiceExact,
    DuplicateInvoicePlausible,
    InvoiceDraftNotReady,
    InvoiceFileTooLarge,
    InvoiceHasBlockingIssues,
    InvoiceRateLimitExceeded,
    UnsupportedInvoiceFileType,
)
from app.models.invoice import InvoiceDraft, InvoiceDraftLine
from app.models.membership import Membership
from app.repositories.invoice import InvoiceDraftLineRepository, InvoiceDraftRepository
from app.repositories.product import ProductRepository
from app.repositories.supplier import SupplierRepository
from app.schemas.invoice import (
    InvoiceConfirmPreview,
    InvoiceConfirmRequest,
    InvoiceConfirmResponse,
    InvoiceDraftLineOut,
    InvoiceDraftOut,
    InvoiceHeaderUpdateRequest,
    InvoiceLineUpdateRequest,
    InvoiceUndoResponse,
)
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

# Tenant-scoped: business_id comes from the URL and is verified by
# get_current_membership (same as every other business-scoped router).
router = APIRouter(prefix="/businesses/{business_id}/invoices", tags=["invoices"])

# Content-type isn't trusted for anything (app/invoices/pdf_reader.py
# checks the real file signature) — this is just a fast, cheap early
# reject for an obviously-wrong upload, same role as the logo route's
# own content-type check.
_ALLOWED_CONTENT_TYPES = {"application/pdf"}


def _get_draft_or_404(db: Session, draft_id: uuid.UUID, business_id: uuid.UUID) -> InvoiceDraft:
    draft = InvoiceDraftRepository(db).get_for_business(draft_id, business_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice draft not found")
    return draft


def _get_line_or_404(db: Session, draft: InvoiceDraft, line_id: uuid.UUID) -> InvoiceDraftLine:
    line = InvoiceDraftLineRepository(db).get_for_draft(draft.business_id, draft.id, line_id)
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice line not found")
    return line


def _to_draft_out(db: Session, draft: InvoiceDraft, lines: list[InvoiceDraftLine]) -> InvoiceDraftOut:
    # One batch product lookup for every matched line, rather than a
    # query per row — same "load once, resolve in memory" shape this
    # codebase already uses everywhere else (e.g. app/imports/importer.py's
    # ProductMatcher).
    matched_ids = {ln.matched_product_id for ln in lines if ln.matched_product_id is not None}
    products_by_id = {}
    if matched_ids:
        for p in ProductRepository(db).list_for_business(draft.business_id):
            if p.id in matched_ids:
                products_by_id[p.id] = p

    supplier_name = None
    if draft.supplier_id is not None:
        supplier = SupplierRepository(db).get_for_business(draft.business_id, draft.supplier_id)
        supplier_name = supplier.name if supplier else None

    out = InvoiceDraftOut.model_validate(draft)
    out.matched_supplier_name = supplier_name
    line_outs = []
    for ln in lines:
        line_out = InvoiceDraftLineOut.model_validate(ln)
        product = products_by_id.get(ln.matched_product_id) if ln.matched_product_id else None
        line_out.matched_product_name = product.name if product else None
        line_out.matched_product_sku = product.sku if product else None
        line_outs.append(line_out)
    out.lines = line_outs
    return out


def _to_preview_out(preview: service.ConfirmPreview) -> InvoiceConfirmPreview:
    return InvoiceConfirmPreview(
        products_to_create=preview.products_to_create,
        products_to_match=preview.products_to_match,
        lines_excluded=preview.lines_excluded,
        supplier_action=preview.supplier_action,
        supplier_name=preview.supplier_name,
        purchase_movement_count=preview.purchase_movement_count,
        invoice_date=preview.invoice_date,
        blocking_issue_count=preview.blocking_issue_count,
        duplicate_status=preview.duplicate_status,
    )


@router.post("", response_model=InvoiceDraftOut, status_code=status.HTTP_201_CREATED)
async def upload_invoice(
    business_id: uuid.UUID,
    file: UploadFile = File(...),
    # require_active_subscription, not plain membership — same "this is
    # the entry point that starts creating new business value" posture as
    # app/api/uploads.py::request_upload/app/api/imports.py::run_import
    # for CSV purchases (spec §5.2: "match the existing purchase-upload
    # permission model").
    membership: Membership = Depends(require_active_subscription),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> InvoiceDraftOut:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a PDF")
    data = await file.read()
    try:
        draft = service.create_invoice_draft(
            db, business_id=business_id, uploaded_by=current_user.id, filename=file.filename or "invoice.pdf",
            file_bytes=data,
        )
    except UnsupportedInvoiceFileType as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be a real PDF") from exc
    except InvoiceFileTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except InvoiceRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many invoice uploads recently — please try again shortly",
        ) from exc
    lines = service.list_invoice_draft_lines(db, draft)
    return _to_draft_out(db, draft, lines)


@router.get("", response_model=list[InvoiceDraftOut])
def list_invoices(
    business_id: uuid.UUID, membership: Membership = Depends(get_current_membership), db: Session = Depends(get_db)
) -> list[InvoiceDraftOut]:
    drafts = service.list_invoice_drafts(db, business_id)
    return [_to_draft_out(db, d, service.list_invoice_draft_lines(db, d)) for d in drafts]


@router.get("/{invoice_id}", response_model=InvoiceDraftOut)
def get_invoice(
    business_id: uuid.UUID, invoice_id: uuid.UUID, membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> InvoiceDraftOut:
    draft = _get_draft_or_404(db, invoice_id, business_id)
    return _to_draft_out(db, draft, service.list_invoice_draft_lines(db, draft))


@router.get("/{invoice_id}/pdf")
def get_invoice_pdf(
    business_id: uuid.UUID, invoice_id: uuid.UUID, membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Response:
    # Tenant-scoped, unlike the company-logo route — a supplier invoice
    # is real commercial data (spec §5.3), never public.
    draft = _get_draft_or_404(db, invoice_id, business_id)
    if draft.status not in ("processing", "needs_review", "failed"):
        # Deleted from R2 once confirmed (retention decision, see
        # app/invoices/service.py::confirm_invoice_import) — 404, not a
        # stale/broken download.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original file is no longer available")
    data = r2_client.download_object(storage_key=draft.storage_key)
    return Response(content=data, media_type="application/pdf")


@router.patch("/{invoice_id}", response_model=InvoiceDraftOut)
def update_invoice_header(
    business_id: uuid.UUID, invoice_id: uuid.UUID, payload: InvoiceHeaderUpdateRequest,
    membership: Membership = Depends(get_current_membership), db: Session = Depends(get_db),
) -> InvoiceDraftOut:
    draft = _get_draft_or_404(db, invoice_id, business_id)
    updates = payload.model_dump(exclude_unset=True)
    try:
        draft = service.update_invoice_draft_header(db, draft, updates)
    except InvoiceDraftNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SupplierNotFound as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier not found") from exc
    return _to_draft_out(db, draft, service.list_invoice_draft_lines(db, draft))


@router.patch("/{invoice_id}/lines/{line_id}", response_model=InvoiceDraftLineOut)
def update_invoice_line(
    business_id: uuid.UUID, invoice_id: uuid.UUID, line_id: uuid.UUID, payload: InvoiceLineUpdateRequest,
    membership: Membership = Depends(get_current_membership), db: Session = Depends(get_db),
) -> InvoiceDraftLineOut:
    draft = _get_draft_or_404(db, invoice_id, business_id)
    line = _get_line_or_404(db, draft, line_id)
    updates = payload.model_dump(exclude_unset=True)
    try:
        line = service.update_invoice_draft_line(db, draft, line, updates)
    except InvoiceDraftNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProductNotFound as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product not found") from exc
    return InvoiceDraftLineOut.model_validate(line)


@router.post("/{invoice_id}/confirm/preview", response_model=InvoiceConfirmPreview)
def preview_confirm(
    business_id: uuid.UUID, invoice_id: uuid.UUID, membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> InvoiceConfirmPreview:
    draft = _get_draft_or_404(db, invoice_id, business_id)
    return _to_preview_out(service.preview_invoice_confirm(db, draft))


@router.post("/{invoice_id}/confirm", response_model=InvoiceConfirmResponse)
def confirm_invoice(
    business_id: uuid.UUID,
    invoice_id: uuid.UUID,
    payload: InvoiceConfirmRequest = InvoiceConfirmRequest(),
    # Same permission tier as the initial upload (spec §5.2) — this is
    # the actual data-writing trigger.
    membership: Membership = Depends(require_active_subscription),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> InvoiceConfirmResponse:
    draft = _get_draft_or_404(db, invoice_id, business_id)
    try:
        draft, result = service.confirm_invoice_import(
            db, draft, confirming_user_id=current_user.id, override_duplicate_warning=payload.override_duplicate_warning
        )
    except InvoiceDraftNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvoiceHasBlockingIssues as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except DuplicateInvoiceExact as exc:
        # Plain string detail — same convention as every other route in
        # this app (frontend/lib/api/client.ts's throwApiError only reads
        # a string `detail`). The draft's own duplicate_status/
        # duplicate_of_draft_id fields (already fetched before the user
        # ever reaches Confirm) are the frontend's real source for which
        # draft this duplicates, not this error body.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This invoice has already been imported"
        ) from exc
    except DuplicateInvoicePlausible as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This looks like a duplicate of an already-imported invoice — confirm again with "
            "override_duplicate_warning to proceed anyway",
        ) from exc
    return InvoiceConfirmResponse(
        invoice_draft_id=draft.id,
        status=draft.status,
        import_record_id=result.import_record_id,
        rows_imported=result.rows_imported,
        rows_rejected=result.rows_rejected,
        rejection_summary=result.rejection_summary,
        preview=_to_preview_out(result.preview),
    )


@router.post("/{invoice_id}/undo", response_model=InvoiceUndoResponse)
def undo_invoice(
    business_id: uuid.UUID, invoice_id: uuid.UUID, membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced), db: Session = Depends(get_db),
) -> InvoiceUndoResponse:
    draft = _get_draft_or_404(db, invoice_id, business_id)
    try:
        draft = service.undo_invoice_import(db, draft, user_id=current_user.id)
    except InvoiceDraftNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ImportNotReversible as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InvoiceUndoResponse(
        invoice_draft_id=draft.id, status=draft.status, import_record_id=draft.import_record_id,
        reversed_at=draft.reversed_at,
    )


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_invoice(
    business_id: uuid.UUID, invoice_id: uuid.UUID, membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced), db: Session = Depends(get_db),
) -> None:
    draft = _get_draft_or_404(db, invoice_id, business_id)
    try:
        service.discard_invoice_draft(db, draft, user_id=current_user.id)
    except InvoiceDraftNotReady as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
