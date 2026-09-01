"""Duplicate/idempotency detection for invoice drafts (spec §4) — checked
before a draft is even shown for review, and re-checked at confirm time
against anything that's been confirmed since. Scoped strictly to this
business (every query below is business_id-filtered, same as every other
table in this schema — no new cross-tenant-leak surface to build or test
differently; a duplicate check can never see another tenant's data by
construction).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.repositories.invoice import InvoiceDraftRepository

# A same-hash match only counts as a real duplicate against a draft
# that's still meaningfully "the same invoice" — a failed extraction
# attempt isn't a real invoice yet (the identical file must be re-
# uploadable after a fix), and a reversed (undone) import is a
# deliberate "redo this" case, not a duplicate to block.
_ACTIVE_HASH_STATUSES = ("processing", "needs_review", "confirmed")


@dataclass(frozen=True)
class DuplicateCheckResult:
    status: str  # "none" | "exact" | "plausible"
    duplicate_of_draft_id: uuid.UUID | None


def check_duplicates(
    repo: InvoiceDraftRepository,
    *,
    business_id: uuid.UUID,
    source_file_hash: str,
    supplier_id: uuid.UUID | None,
    invoice_reference: str | None,
    invoice_date: date | None,
    currency: str | None,
    grand_total: Decimal | None,
    exclude_draft_id: uuid.UUID | None = None,
) -> DuplicateCheckResult:
    # (a) exact — identical file bytes (spec §4's "source-file hash").
    # exclude_draft_id matters here specifically: every caller checks a
    # draft that already exists in the table by the time this runs (its
    # own row was created before extraction), so without excluding its
    # own id, a draft would always trivially match its own hash.
    existing_by_hash = repo.find_by_source_file_hash(business_id, source_file_hash, exclude_id=exclude_draft_id)
    if existing_by_hash is not None and existing_by_hash.status in _ACTIVE_HASH_STATUSES:
        return DuplicateCheckResult(status="exact", duplicate_of_draft_id=existing_by_hash.id)

    # (b) exact — same normalised supplier + invoice reference, already
    # confirmed (only checked against confirmed drafts: two independent,
    # still-unreviewed uploads that happen to share a typo'd reference
    # shouldn't block each other before either is a real import yet).
    if invoice_reference:
        existing_by_reference = repo.find_confirmed_by_reference(
            business_id, supplier_id=supplier_id, invoice_reference=invoice_reference
        )
        if existing_by_reference is not None:
            return DuplicateCheckResult(status="exact", duplicate_of_draft_id=existing_by_reference.id)

    # (c) plausible — same date + currency + grand total, already
    # confirmed. A warning, never an auto-block — confirm requires an
    # explicit override (app/invoices/service.py::confirm_invoice_import),
    # mirroring app/imports/service.py::confirm_mapping's
    # confirm_multiple_locations escape-hatch shape exactly.
    if invoice_date is not None and grand_total is not None:
        plausible = repo.find_plausible_duplicates(
            business_id, invoice_date=invoice_date, currency=currency, grand_total=grand_total
        )
        if plausible:
            return DuplicateCheckResult(status="plausible", duplicate_of_draft_id=plausible[0].id)

    return DuplicateCheckResult(status="none", duplicate_of_draft_id=None)
