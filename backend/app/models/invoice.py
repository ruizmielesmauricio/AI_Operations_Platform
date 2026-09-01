from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, JSON, Date, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

# Mirrors ImportRecord's "pending"/"mapped"/"completed"/"reversed" style,
# adapted for a PDF's genuinely different lifecycle — there's no column-
# mapping stage, but there IS a synchronous "we're reading the file right
# now" moment CSV import never has (see app/invoices/service.py).
INVOICE_DRAFT_STATUSES = ("processing", "needs_review", "failed", "confirmed", "reversed")

# Machine-readable (CLAUDE.md convention), set only when status == "failed".
INVOICE_FAILURE_REASONS = (
    "encrypted",
    "corrupt",
    "oversized",
    "unsupported_file_type",
    "no_extractable_text",
    "multi_invoice_suspected",
)

DUPLICATE_STATUSES = ("none", "exact", "plausible")

LINE_RESOLUTION_ACTIONS = ("match_existing", "create_new", "excluded", "unresolved")


class InvoiceDraft(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A durable draft/review record for one uploaded supplier-invoice PDF
    (PDF Supplier-Invoice Ingestion spec, §2) — retains extraction
    provenance without duplicating the final purchase ledger. Confirming
    (app/invoices/service.py::confirm_invoice_import) hands its lines to
    the SAME app/imports/importer.py::write_purchases_batch every CSV
    purchases import already uses, via a real Upload+ImportRecord pair
    (import_record_id below) — so this table is a review staging area,
    never a second source of truth for what was actually purchased.

    Provenance fields (extracted_header, and each InvoiceDraftLine's own
    extracted_fields) hold {raw, value, confidence, issue} per field —
    same JSON-provenance-plus-typed-final-value shape ImportMappingProfile
    already uses for column_mapping, not a rigid column per attribute.
    The typed columns below are the user-editable, currently-proposed
    values the review screen reads/writes directly.
    """

    __tablename__ = "invoice_drafts"

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(64), nullable=False)
    # sha256 hex digest of the raw PDF bytes — the exact-duplicate signal
    # (spec §4). Indexed for the duplicate-check query.
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parser_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extracted_header: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Draft-level issue codes (arithmetic mismatches, "no line-item table
    # detected") — distinct from InvoiceDraftLine.issue_code, which is
    # per-line. A user correction to a header field re-runs this list
    # (app/invoices/service.py); confirm blocks while a blocking code is
    # still present, same "surface, never silently correct" posture as
    # every other validation in this codebase.
    header_issue_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Unknown supplier stays valid here too (spec: "must never become
    # mandatory solely because an invoice is imported") — supplier_id is
    # nullable, matching InventoryMovement.supplier_id's own nullability.
    supplier_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    supplier_name_input: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    tax_total: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    discount_total: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    shipping_total: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    grand_total: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)

    duplicate_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    # Self-FK — the earlier draft/import this one plausibly or exactly
    # duplicates, per app/invoices/duplicates.py. No ondelete cascade
    # (matches this schema's own convention — see 06_Database_Design.md;
    # no business_id FK anywhere cascades either).
    duplicate_of_draft_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoice_drafts.id"), nullable=True
    )

    # Set once confirmed — the trace-back link (spec §6) from a purchase
    # batch back to the invoice it came from, and the FK undo_invoice_
    # import resolves to call the existing importer.undo_import unchanged.
    import_record_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_records.id"), nullable=True
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvoiceDraftLine(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """One extracted (or manually added) line item on an InvoiceDraft.
    resolution_action starts "unresolved" for every extracted line — the
    review screen is where a user picks match_existing/create_new/
    excluded (spec §3.5); confirm blocks while any non-excluded line is
    still "unresolved" (app/invoices/service.py).
    """

    __tablename__ = "invoice_draft_lines"

    invoice_draft_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoice_drafts.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extracted_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Decimal, not Integer, at the draft stage — an extracted quantity may
    # genuinely be fractional (e.g. a weight-based line); InventoryMovement.
    # quantity_delta is Integer, so a non-whole value is surfaced as a
    # blocking issue_code at confirm time (never silently rounded — see
    # app/invoices/extraction.py's arithmetic validation).
    quantity: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 4), nullable=True)
    line_total: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    tax_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(6, 3), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(DECIMAL(12, 2), nullable=True)

    resolution_action: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    matched_product_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=True)
    # Only meaningful when resolution_action == "create_new" — user-
    # editable proposal, defaults from extraction but never auto-applied
    # without this explicit action (spec §3.5: "explicit confirmation").
    proposed_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposed_sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issue_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
