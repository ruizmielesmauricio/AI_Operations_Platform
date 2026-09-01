# Mirrors app/imports/exceptions.py's shape — one exception per failure
# mode the review screen needs to tell apart, each mapping to a machine-
# readable app.models.invoice.INVOICE_FAILURE_REASONS code
# (app/invoices/service.py catches these and writes the code, never lets
# one bubble up as a generic 500).


class UnsupportedInvoiceFileType(Exception):
    """Raised when the upload isn't a .pdf, or its real file signature
    (magic bytes) doesn't match one — checked on content, never trusted
    from the filename alone (spec §1.4)."""


class InvoiceFileTooLarge(Exception):
    def __init__(self, size_bytes: int, limit_bytes: int):
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(f"File is {size_bytes} bytes, over the {limit_bytes}-byte limit")


class InvoiceTooManyPages(Exception):
    """Decompression/resource-exhaustion guard (spec §5.5) — a genuine
    supplier invoice is realistically 1-10 pages; a document far past
    that is either not an invoice or a deliberately hostile file, either
    way not something to spend server CPU parsing in full."""

    def __init__(self, page_count: int, limit: int):
        self.page_count = page_count
        self.limit = limit
        super().__init__(f"PDF has {page_count} pages, over the {limit}-page limit")


class EncryptedPdf(Exception):
    """Raised when the PDF requires a password pdfminer doesn't have."""


class CorruptPdf(Exception):
    """Raised when the PDF's structure can't be parsed at all — malformed,
    truncated, or not really a PDF despite passing the signature check."""


class NoExtractableText(Exception):
    """Raised when every page has no (or negligible) embedded text —
    almost certainly a scanned/image-only PDF. v1 has no OCR fallback
    (deferred, per the confirmed scope decision) — this becomes an honest
    "can't read this yet" rejection, never a guess."""


class InvoiceDraftNotReady(Exception):
    """Raised when confirm/discard is attempted on a draft whose status
    doesn't allow it (e.g. confirming a still-"processing" or already-
    "confirmed" draft)."""

    def __init__(self, status: str):
        self.status = status
        super().__init__(f"Invoice draft is not ready for this action (status={status})")


class InvoiceHasBlockingIssues(Exception):
    """Raised by confirm_invoice_import when any non-excluded line is
    still "unresolved" or carries a blocking issue_code (spec §3.9:
    "Disable confirmation while blocking errors remain")."""

    def __init__(self, line_ids: list) -> None:
        self.line_ids = line_ids
        super().__init__(f"{len(line_ids)} line(s) have unresolved blocking issues")


class DuplicateInvoiceExact(Exception):
    """Raised by confirm_invoice_import when this invoice is an exact
    duplicate of an already-confirmed one (spec §4) — never silently
    imported twice, and never overridable (unlike a plausible duplicate)."""

    def __init__(self, duplicate_of_draft_id) -> None:
        self.duplicate_of_draft_id = duplicate_of_draft_id
        super().__init__(f"Exact duplicate of an already-confirmed invoice ({duplicate_of_draft_id})")


class DuplicateInvoicePlausible(Exception):
    """Raised by confirm_invoice_import when this invoice plausibly
    duplicates an already-confirmed one and the caller didn't pass
    override_duplicate_warning=True — mirrors confirm_mapping's
    confirm_multiple_locations escape-hatch shape exactly."""

    def __init__(self, duplicate_of_draft_id) -> None:
        self.duplicate_of_draft_id = duplicate_of_draft_id
        super().__init__(f"Plausible duplicate of an already-confirmed invoice ({duplicate_of_draft_id})")


class InvoiceRateLimitExceeded(Exception):
    """Raised when a business has uploaded too many invoice PDFs in the
    rate-limit window (spec §5.5)."""
