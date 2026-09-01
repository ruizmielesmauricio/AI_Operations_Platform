"""Covers app/invoices/pdf_reader.py's validation/extraction gates
directly, against realistic generated PDF fixtures (tests/
invoice_pdf_helpers.py) — text-native, encrypted, corrupt, image-only
(no OCR fallback exists — must be an honest rejection), oversized, wrong
file type, too many pages.
"""

import pytest

from app.invoices import pdf_reader
from app.invoices.exceptions import (
    CorruptPdf,
    EncryptedPdf,
    InvoiceFileTooLarge,
    InvoiceTooManyPages,
    NoExtractableText,
    UnsupportedInvoiceFileType,
)
from tests.invoice_pdf_helpers import (
    build_corrupt_pdf,
    build_encrypted_pdf,
    build_image_only_pdf,
    build_invoice_pdf,
    build_many_pages_pdf,
    not_a_pdf_bytes,
)


def test_valid_text_native_pdf_reads_cleanly():
    result = pdf_reader.read_pdf(build_invoice_pdf())

    assert result.page_count == 1
    assert "Acme Bike Parts Ltd" in result.pages[0].text
    assert len(result.source_file_hash) == 64  # sha256 hex digest


def test_file_hash_is_deterministic_for_identical_bytes():
    data = build_invoice_pdf()

    assert pdf_reader.compute_file_hash(data) == pdf_reader.compute_file_hash(data)


def test_file_hash_differs_for_different_bytes():
    a = pdf_reader.compute_file_hash(build_invoice_pdf(invoice_reference="INV-1"))
    b = pdf_reader.compute_file_hash(build_invoice_pdf(invoice_reference="INV-2"))

    assert a != b


def test_wrong_file_signature_is_rejected_before_any_parsing():
    # A renamed .exe/.csv/anything must never reach the PDF parser at
    # all — checked on real bytes, never the filename (spec §1.4).
    with pytest.raises(UnsupportedInvoiceFileType):
        pdf_reader.read_pdf(not_a_pdf_bytes())


def test_oversized_file_is_rejected():
    oversized = b"%PDF-" + b"0" * (pdf_reader.MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(InvoiceFileTooLarge):
        pdf_reader.read_pdf(oversized)


def test_encrypted_pdf_is_rejected_with_a_specific_reason():
    with pytest.raises(EncryptedPdf):
        pdf_reader.read_pdf(build_encrypted_pdf())


def test_corrupt_truncated_pdf_is_rejected_with_a_specific_reason():
    with pytest.raises(CorruptPdf):
        pdf_reader.read_pdf(build_corrupt_pdf())


def test_image_only_pdf_with_no_text_is_rejected_honestly_not_guessed():
    # No OCR fallback exists in v1 (confirmed scope decision) — this must
    # be a clear, typed rejection, never a silent empty/garbage result.
    with pytest.raises(NoExtractableText):
        pdf_reader.read_pdf(build_image_only_pdf())


def test_pdf_with_too_many_pages_is_rejected():
    with pytest.raises(InvoiceTooManyPages):
        pdf_reader.read_pdf(build_many_pages_pdf(pdf_reader._MAX_PAGES + 1))


def test_a_pdf_at_the_page_limit_is_accepted():
    result = pdf_reader.read_pdf(build_many_pages_pdf(pdf_reader._MAX_PAGES))
    assert result.page_count == pdf_reader._MAX_PAGES
