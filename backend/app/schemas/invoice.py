import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InvoiceDraftLineOut(BaseModel):
    id: uuid.UUID
    line_number: int
    extracted_fields: dict | None = None
    description: str | None = None
    supplier_sku: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    discount_amount: Decimal | None = None
    resolution_action: str
    matched_product_id: uuid.UUID | None = None
    # Resolved server-side (app/api/invoices.py) from matched_product_id
    # — the review screen has no other way to show a friendly name for
    # an auto-matched line (spec §3.6/§3.4: "show clearly whether the
    # supplier is an existing match..."; the same clarity applies to a
    # matched product). None whenever matched_product_id is None.
    matched_product_name: str | None = None
    matched_product_sku: str | None = None
    proposed_name: str | None = None
    proposed_sku: str | None = None
    issue_code: str | None = None

    model_config = {"from_attributes": True}


class InvoiceDraftOut(BaseModel):
    id: uuid.UUID
    original_filename: str
    status: str
    failure_reason: str | None = None
    extracted_at: datetime | None = None
    extracted_header: dict | None = None
    header_issue_codes: list[str] | None = None
    supplier_id: uuid.UUID | None = None
    # Resolved server-side (app/api/invoices.py) from supplier_id, same
    # reasoning as InvoiceDraftLineOut.matched_product_name — None
    # whenever supplier_id is None (nothing matched; supplier_name_input
    # is the only signal in that case, e.g. a proposed new supplier).
    matched_supplier_name: str | None = None
    supplier_name_input: str | None = None
    invoice_reference: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    discount_total: Decimal | None = None
    shipping_total: Decimal | None = None
    grand_total: Decimal | None = None
    duplicate_status: str
    duplicate_of_draft_id: uuid.UUID | None = None
    import_record_id: uuid.UUID | None = None
    reversed_at: datetime | None = None
    created_at: datetime
    lines: list[InvoiceDraftLineOut] = []

    model_config = {"from_attributes": True}


class InvoiceHeaderUpdateRequest(BaseModel):
    """PATCH /invoices/{id} — same "only touch what's actually sent"
    convention as BusinessProfileUpdate (app/schemas/business.py):
    app/invoices/service.py::update_invoice_draft_header only writes keys
    present via model_dump(exclude_unset=True); a field explicitly sent
    as null clears it, an omitted field is left untouched.
    """

    supplier_id: uuid.UUID | None = None
    supplier_name_input: str | None = Field(default=None, max_length=255)
    invoice_reference: str | None = Field(default=None, max_length=128)
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, max_length=8)
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    discount_total: Decimal | None = None
    shipping_total: Decimal | None = None
    grand_total: Decimal | None = None


class InvoiceLineUpdateRequest(BaseModel):
    """PATCH /invoices/{id}/lines/{line_id} — same partial-update
    convention as InvoiceHeaderUpdateRequest above."""

    description: str | None = Field(default=None, max_length=500)
    supplier_sku: str | None = Field(default=None, max_length=128)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=32)
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    discount_amount: Decimal | None = None
    # "match_existing" | "create_new" | "excluded" | "unresolved" (spec
    # §3.5) — validated against app.models.invoice.LINE_RESOLUTION_ACTIONS
    # in app/invoices/service.py, not a Pydantic Literal, so the accepted
    # set lives in one place as it evolves (same reasoning as Upload.
    # entity_type's own plain-str validation).
    resolution_action: str | None = Field(default=None, max_length=16)
    matched_product_id: uuid.UUID | None = None
    proposed_name: str | None = Field(default=None, max_length=255)
    proposed_sku: str | None = Field(default=None, max_length=128)


class InvoiceConfirmRequest(BaseModel):
    # Mirrors ConfirmMappingRequest.confirm_multiple_locations' escape-
    # hatch shape exactly (app/schemas/import_mapping.py) — required
    # explicitly true to proceed past a "plausible duplicate" warning,
    # never implied by any other field.
    override_duplicate_warning: bool = False


class InvoiceConfirmPreview(BaseModel):
    """§3.8's "list exactly what will happen" impact summary — returned
    by both the dry-run preview and, once it actually writes, alongside
    the real result, so the frontend can render the identical summary
    either way."""

    products_to_create: int
    products_to_match: int
    lines_excluded: int
    supplier_action: str  # "match_existing" | "create_new" | "unknown"
    supplier_name: str | None = None
    purchase_movement_count: int
    invoice_date: date | None = None
    blocking_issue_count: int
    duplicate_status: str


class InvoiceConfirmResponse(BaseModel):
    invoice_draft_id: uuid.UUID
    status: str
    import_record_id: uuid.UUID
    rows_imported: int
    rows_rejected: int
    rejection_summary: dict | None = None
    preview: InvoiceConfirmPreview


class InvoiceUndoResponse(BaseModel):
    invoice_draft_id: uuid.UUID
    status: str
    import_record_id: uuid.UUID
    reversed_at: datetime | None
