"""Direct boundary to the PDF-parsing library (pdfplumber/pdfminer) — no
other module in this codebase imports it (CLAUDE.md: no provider SDK
outside its dedicated client module). Text extraction only: no OCR path
exists here (see docs/governance/11_Development_Roadmap.md's changelog
entry for this feature — deferred, confirmed with the user).

Every failure mode is turned into one of this package's typed exceptions
(app/invoices/exceptions.py) — never a raw pdfminer/pdfplumber exception
crossing into app/invoices/service.py, and never extracted text/bytes
logged anywhere (spec §5.4).
"""

import hashlib
import io
from dataclasses import dataclass, field as dataclass_field

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from app.invoices.exceptions import (
    CorruptPdf,
    EncryptedPdf,
    InvoiceFileTooLarge,
    InvoiceTooManyPages,
    NoExtractableText,
    UnsupportedInvoiceFileType,
)

_PDF_MAGIC = b"%PDF-"

# Matches app/imports/service.py's own detection-window size ceiling —
# same "one bounded synchronous read, no background job queue" reasoning.
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

# A genuine supplier invoice is realistically 1-10 pages. Past this is
# either not an invoice or a resource-exhaustion attempt (spec §5.5) —
# rejected before any page is parsed, not truncated silently.
_MAX_PAGES = 30

# Per-page-averaged character count below which a PDF is treated as
# "no extractable text" (almost certainly scanned/image-only) rather than
# a genuinely sparse but real text-native page. Deliberately low: a
# one-line "PAID" stamp page mixed into an otherwise text-native invoice
# must not tip the average below this on its own.
_MIN_AVG_CHARS_FOR_TEXT_NATIVE = 20


@dataclass(frozen=True)
class PdfWord:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True)
class PdfPageText:
    page_number: int  # 1-indexed, matches how a human would refer to it
    text: str
    words: list[PdfWord] = dataclass_field(default_factory=list)
    tables: list[list[list[str | None]]] = dataclass_field(default_factory=list)


@dataclass(frozen=True)
class PdfReadResult:
    pages: list[PdfPageText]
    page_count: int
    source_file_hash: str


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def read_pdf(file_bytes: bytes) -> PdfReadResult:
    """Validates and extracts one PDF's text/word-position/table content.
    Raises a typed app/invoices/exceptions.py exception for every failure
    mode the spec calls out (§1.4): oversized, wrong/spoofed file type,
    encrypted, corrupt, or no extractable text at all. Never raises a raw
    library exception.
    """
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise InvoiceFileTooLarge(len(file_bytes), MAX_FILE_SIZE_BYTES)
    if not file_bytes.startswith(_PDF_MAGIC):
        # Real file-signature check, not the filename/extension — a
        # renamed .exe or .csv must not reach the parser at all.
        raise UnsupportedInvoiceFileType()

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if len(pdf.pages) > _MAX_PAGES:
                raise InvoiceTooManyPages(len(pdf.pages), _MAX_PAGES)
            pages: list[PdfPageText] = []
            total_chars = 0
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                total_chars += len(text.strip())
                words = [
                    PdfWord(text=w["text"], x0=w["x0"], x1=w["x1"], top=w["top"], bottom=w["bottom"])
                    for w in page.extract_words()
                ]
                tables = page.extract_tables() or []
                pages.append(PdfPageText(page_number=i, text=text, words=words, tables=tables))
    except InvoiceTooManyPages:
        raise
    except (PDFPasswordIncorrect, PDFEncryptionError) as exc:
        raise EncryptedPdf() from exc
    except (PdfminerException, MalformedPDFException) as exc:
        # pdfplumber wraps the real pdfminer exception as this call's
        # single arg (confirmed via pdfplumber.pdf.PDF.__init__'s own
        # `raise PdfminerException(e)`) rather than raising it directly —
        # unwrap one level to tell "wrong password" apart from "genuinely
        # malformed," rather than lumping both under "corrupt."
        inner = exc.args[0] if exc.args else None
        if isinstance(inner, (PDFPasswordIncorrect, PDFEncryptionError)):
            raise EncryptedPdf() from exc
        raise CorruptPdf() from exc
    except Exception as exc:
        # Last-resort net: a malformed file fed to a C-backed parser
        # (pypdfium2, pdfplumber's table-finder) can raise almost
        # anything — never let an unrecognised exception type surface as
        # an unhandled 500 for what is, from the user's perspective, just
        # a bad file.
        raise CorruptPdf() from exc

    if pages and (total_chars / len(pages)) < _MIN_AVG_CHARS_FOR_TEXT_NATIVE:
        raise NoExtractableText()

    return PdfReadResult(pages=pages, page_count=len(pages), source_file_hash=compute_file_hash(file_bytes))
