"""Turns a app/invoices/pdf_reader.py::PdfReadResult into structured,
proposed invoice data — pure functions, no I/O (same layering as
app/imports/detection.py, one level below the file-reading boundary).

Every field carries provenance (raw text, typed value, a confidence
signal, and a reason when it's missing/ambiguous) rather than a bare
value — the spec's own required shape (§2) — reusing the *existing*,
already-tested app/imports/value_parsers.py::parse_date/parse_money for
the actual "turn this raw string into a typed value" step, exactly the
way app/imports/detection.py already does for spreadsheet columns.

Line-item extraction only trusts pdfplumber's ruled-table detection —
deliberately NOT a word-position column-clustering fallback. A half-built
layout heuristic risks silently misattributing a value to the wrong
column, which is worse than an honest "couldn't detect a line-item table"
state (the spec's own repeated instruction: never manufacture a value,
never silently choose a weak match). A table-less invoice becomes a
draft with zero auto-extracted lines and a header issue code — the
review screen lets a line be added manually.
"""

import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date
from decimal import Decimal

from app.imports.value_parsers import parse_date, parse_int, parse_money
from app.invoices.pdf_reader import PdfReadResult

PARSER_VERSION = 1


@dataclass(frozen=True)
class FieldProvenance:
    raw: str | None
    value: object | None  # Decimal | date | str | None — already typed
    confidence: float
    issue: str | None = None

    def to_json(self) -> dict:
        value = self.value
        if isinstance(value, (Decimal, date)):
            value = str(value)
        return {"raw": self.raw, "value": value, "confidence": self.confidence, "issue": self.issue}


def _missing(issue: str = "not_found") -> FieldProvenance:
    return FieldProvenance(raw=None, value=None, confidence=0.0, issue=issue)


@dataclass
class ExtractedLine:
    line_number: int
    description: FieldProvenance
    supplier_sku: FieldProvenance
    quantity: FieldProvenance
    unit: FieldProvenance
    unit_price: FieldProvenance
    line_total: FieldProvenance
    tax_rate: FieldProvenance
    tax_amount: FieldProvenance
    discount_amount: FieldProvenance
    issue_code: str | None = None


@dataclass
class ExtractedInvoice:
    supplier_name: FieldProvenance
    invoice_reference: FieldProvenance
    invoice_date: FieldProvenance
    due_date: FieldProvenance
    currency: FieldProvenance
    subtotal: FieldProvenance
    tax_total: FieldProvenance
    discount_total: FieldProvenance
    shipping_total: FieldProvenance
    grand_total: FieldProvenance
    lines: list[ExtractedLine] = dataclass_field(default_factory=list)
    header_issue_codes: list[str] = dataclass_field(default_factory=list)


# --- Header field extraction --------------------------------------------
#
# One or more label patterns per field, checked in this priority order so
# a specific label ("Subtotal", "Due Date") claims its line before a
# looser catch-all ("Total", "Date") can steal it — see _extract_header.

_HEADER_FIELD_ORDER = (
    "invoice_reference",
    "due_date",
    "invoice_date",
    "subtotal",
    "discount_total",
    "shipping_total",
    "tax_total",
    "grand_total",
)

_LABEL_PATTERNS: dict[str, list[re.Pattern]] = {
    "invoice_reference": [
        re.compile(r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*(.+)", re.I),
    ],
    "due_date": [
        re.compile(r"due\s*date\s*[:\-]?\s*(.+)", re.I),
        re.compile(r"payment\s*due\s*[:\-]?\s*(.+)", re.I),
    ],
    "invoice_date": [
        re.compile(r"invoice\s*date\s*[:\-]?\s*(.+)", re.I),
        re.compile(r"^date\s*[:\-]?\s*(.+)", re.I),
    ],
    "subtotal": [
        re.compile(r"sub\s*-?\s*total\s*[:\-]?\s*(.+)", re.I),
    ],
    "discount_total": [
        re.compile(r"discount\s*[:\-]?\s*(.+)", re.I),
    ],
    "shipping_total": [
        re.compile(r"(?:shipping|freight|delivery)\s*[:\-]?\s*(.+)", re.I),
    ],
    "tax_total": [
        re.compile(r"\b(?:vat|tax|gst)\b\s*(?:total|amount)?\s*[:\-]?\s*(.+)", re.I),
    ],
    "grand_total": [
        re.compile(r"(?:grand\s*total|total\s*due|amount\s*due)\s*[:\-]?\s*(.+)", re.I),
        re.compile(r"^total\s*[:\-]?\s*(.+)", re.I),
    ],
}

_DATE_FIELDS = {"invoice_date", "due_date"}
_MONEY_FIELDS = {"subtotal", "discount_total", "shipping_total", "tax_total", "grand_total"}

_CURRENCY_SYMBOLS = {"€": "EUR", "£": "GBP", "$": "USD"}
_SUPPLIER_LABEL_RE = re.compile(r"(?:from|supplier|vendor|sold\s*by)\s*[:\-]\s*(.+)", re.I)
# A line that's clearly part of the invoice's own boilerplate, never a
# supplier's own name — excluded from the "first real line" fallback.
_NOT_A_SUPPLIER_NAME_RE = re.compile(r"invoice|date|page\s*\d|purchase\s*order", re.I)


def _build_money_provenance(raw: str) -> FieldProvenance:
    value = parse_money(raw)
    if value is None:
        return FieldProvenance(raw=raw, value=None, confidence=0.3, issue="unparseable")
    return FieldProvenance(raw=raw, value=value, confidence=0.9)


def _build_date_provenance(raw: str) -> FieldProvenance:
    value = parse_date(raw)
    if value is None:
        return FieldProvenance(raw=raw, value=None, confidence=0.3, issue="unparseable")
    return FieldProvenance(raw=raw, value=value, confidence=0.9)


def _detect_currency(all_text: str) -> FieldProvenance:
    counts = {symbol: all_text.count(symbol) for symbol in _CURRENCY_SYMBOLS}
    best_symbol, best_count = max(counts.items(), key=lambda kv: kv[1])
    if best_count > 0:
        return FieldProvenance(raw=best_symbol, value=_CURRENCY_SYMBOLS[best_symbol], confidence=0.7)
    for code in ("EUR", "GBP", "USD"):
        if re.search(rf"\b{code}\b", all_text):
            return FieldProvenance(raw=code, value=code, confidence=0.6)
    return _missing("no_currency_signal")


def _detect_supplier_name(lines: list[str]) -> FieldProvenance:
    for line in lines:
        m = _SUPPLIER_LABEL_RE.search(line)
        if m:
            candidate = m.group(1).strip()
            if candidate:
                return FieldProvenance(raw=candidate, value=candidate, confidence=0.75)
    # Low-confidence fallback: the first substantial, non-boilerplate line
    # on the document — commonly a letterhead name. Deliberately marked
    # low-confidence rather than omitted — a wrong guess here costs
    # nothing (the review screen always requires an explicit supplier
    # match/create choice, spec §3.6), but a plausible starting point
    # saves genuine re-typing in the common case.
    for line in lines:
        stripped = line.strip()
        if len(stripped) >= 3 and not _NOT_A_SUPPLIER_NAME_RE.search(stripped) and not stripped[0].isdigit():
            return FieldProvenance(raw=stripped, value=stripped, confidence=0.3, issue="low_confidence_fallback")
    return _missing("no_supplier_signal")


def _extract_header(all_lines: list[str], all_text: str) -> tuple[dict[str, FieldProvenance], list[str]]:
    claimed: set[int] = set()
    result: dict[str, FieldProvenance] = {}
    for field in _HEADER_FIELD_ORDER:
        found: tuple[int, str] | None = None
        for pattern in _LABEL_PATTERNS[field]:
            for idx, line in enumerate(all_lines):
                if idx in claimed:
                    continue
                m = pattern.search(line)
                if m:
                    found = (idx, m.group(1).strip())
                    break
            if found:
                break
        if found is None:
            result[field] = _missing()
            continue
        idx, raw = found
        claimed.add(idx)
        if not raw:
            result[field] = FieldProvenance(raw=None, value=None, confidence=0.2, issue="label_found_no_value")
            continue
        if field in _DATE_FIELDS:
            result[field] = _build_date_provenance(raw)
        elif field in _MONEY_FIELDS:
            result[field] = _build_money_provenance(raw)
        else:
            # invoice_reference — a plain string, not date/money typed.
            result[field] = FieldProvenance(raw=raw, value=raw, confidence=0.85)

    result["supplier_name"] = _detect_supplier_name(all_lines)
    result["currency"] = _detect_currency(all_text)

    issues = [f for f, prov in result.items() if prov.issue == "unparseable"]
    return result, issues


# --- Line-item extraction (ruled tables only — see module docstring) ----

_COLUMN_TOKENS: dict[str, set[str]] = {
    "supplier_sku": {"sku", "code", "item no", "part no", "part number", "product code", "item code"},
    "quantity": {"qty", "quantity", "units"},
    "unit": {"unit", "uom"},
    "unit_price": {"unit price", "price", "rate", "unit cost", "each"},
    "tax_rate": {"vat rate", "tax rate", "vat %", "tax %"},
    "tax_amount": {"vat", "tax", "vat amt", "tax amt"},
    "discount_amount": {"discount", "disc"},
    "line_total": {"amount", "total", "line total", "net amount", "extended", "ext price"},
    "description": {"description", "item", "product", "details", "particulars"},
}
# Priority order: more specific tokens claim a header cell before a
# looser one can. "unit_price" must be checked before "unit" — a header
# literally reading "Unit Price" contains "unit" as a whole word, so
# "unit" alone would otherwise steal it; "tax_rate" before "tax_amount"
# for the same reason ("VAT Rate" contains "vat"); "unit_price"/
# "tax_amount"/"discount_amount" all before "line_total", whose "total"/
# "amount" tokens are the loosest catch-all.
_COLUMN_FIELD_ORDER = (
    "supplier_sku",
    "quantity",
    "unit_price",
    "unit",
    "tax_rate",
    "tax_amount",
    "discount_amount",
    "line_total",
    "description",
)


def _token_matches(header: str, token: str) -> bool:
    # A multi-word token ("unit price") is checked as a substring; a
    # single-word one is checked against the header's own word set —
    # same "whole word, not a fragment" discipline app/imports/
    # detection.py's _token_overlap already applies, so a single-word
    # token like "unit" doesn't accidentally fire on an unrelated header
    # that merely contains those letters.
    if " " in token:
        return token in header
    return token in header.split()


def _match_columns(header_row: list[str | None]) -> dict[int, str]:
    normalized = [(h or "").strip().lower() for h in header_row]
    column_for_field: dict[str, int] = {}
    field_for_column: dict[int, str] = {}
    for field in _COLUMN_FIELD_ORDER:
        tokens = _COLUMN_TOKENS[field]
        for col_idx, header in enumerate(normalized):
            if not header or col_idx in field_for_column:
                continue
            if any(_token_matches(header, token) for token in tokens):
                column_for_field[field] = col_idx
                field_for_column[col_idx] = field
                break
    return field_for_column


def _pick_line_items_table(pages) -> tuple[list[list[str | None]], dict[int, str]] | None:
    """The largest ruled table across every page, by data-row count —
    invoice line-item tables are typically the biggest table on the
    document. Requires at least one recognisable column (quantity, price,
    or total) — a 2-column "bank details" table must never be mistaken
    for line items."""
    best: tuple[list[list[str | None]], dict[int, str]] | None = None
    best_rows = 0
    for page in pages:
        for table in page.tables:
            if len(table) < 2:
                continue
            field_for_column = _match_columns(table[0])
            if not ({"quantity", "unit_price", "line_total"} & set(field_for_column.values())):
                continue
            data_rows = len(table) - 1
            if data_rows > best_rows:
                best = (table, field_for_column)
                best_rows = data_rows
    return best


def _cell(row: list[str | None], field_for_column: dict[int, str], field: str) -> str | None:
    for col_idx, f in field_for_column.items():
        if f == field and col_idx < len(row):
            value = row[col_idx]
            return value.strip() if isinstance(value, str) else None
    return None


def _line_provenance_money(raw: str | None) -> FieldProvenance:
    if raw is None or raw == "":
        return _missing()
    return _build_money_provenance(raw)


def _extract_lines(pages) -> tuple[list[ExtractedLine], list[str]]:
    picked = _pick_line_items_table(pages)
    if picked is None:
        return [], ["line_items_not_detected"]

    table, field_for_column = picked
    lines: list[ExtractedLine] = []
    for row_idx, row in enumerate(table[1:], start=1):
        if not any((c or "").strip() for c in row):
            continue  # blank row inside the table (spacer), not a real line
        description_raw = _cell(row, field_for_column, "description")
        quantity_raw = _cell(row, field_for_column, "quantity")
        quantity_value = parse_money(quantity_raw) if quantity_raw else None  # Decimal — may be fractional
        quantity_prov = (
            _missing()
            if quantity_raw is None
            else (
                FieldProvenance(raw=quantity_raw, value=quantity_value, confidence=0.85)
                if quantity_value is not None
                else FieldProvenance(raw=quantity_raw, value=None, confidence=0.3, issue="unparseable")
            )
        )
        line = ExtractedLine(
            line_number=row_idx,
            description=(
                FieldProvenance(raw=description_raw, value=description_raw, confidence=0.8)
                if description_raw
                else _missing()
            ),
            supplier_sku=(
                FieldProvenance(raw=_cell(row, field_for_column, "supplier_sku"), value=_cell(row, field_for_column, "supplier_sku"), confidence=0.85)
                if _cell(row, field_for_column, "supplier_sku")
                else _missing()
            ),
            quantity=quantity_prov,
            unit=(
                FieldProvenance(raw=_cell(row, field_for_column, "unit"), value=_cell(row, field_for_column, "unit"), confidence=0.7)
                if _cell(row, field_for_column, "unit")
                else _missing()
            ),
            unit_price=_line_provenance_money(_cell(row, field_for_column, "unit_price")),
            line_total=_line_provenance_money(_cell(row, field_for_column, "line_total")),
            tax_rate=_line_provenance_money(_cell(row, field_for_column, "tax_rate")),
            tax_amount=_line_provenance_money(_cell(row, field_for_column, "tax_amount")),
            discount_amount=_line_provenance_money(_cell(row, field_for_column, "discount_amount")),
        )
        if line.description.value is None and line.quantity.value is None and line.unit_price.value is None:
            continue  # every recognisable field empty -- not a real line
        _apply_line_issue_codes(line)
        lines.append(line)

    # Re-number sequentially after skipping blank/empty rows, so gaps in
    # the source table never leak into the user-facing line numbering.
    for i, line in enumerate(lines, start=1):
        line.line_number = i
    return lines, []


def compute_line_issue_code(
    *, description: str | None, quantity: Decimal | None, unit_price: Decimal | None, line_total: Decimal | None
) -> str | None:
    """Pure, plain-value version reused by both initial extraction
    (_apply_line_issue_codes below) and app/invoices/service.py's post-
    edit recompute (a PATCH to one line must re-run the same checks
    against whatever the user just typed, not only at extraction time)."""
    if description is None:
        return "missing_description"
    if quantity is None:
        return "missing_quantity"
    if unit_price is None and line_total is None:
        return "missing_price"
    if quantity < 0:
        return "negative_quantity"
    if unit_price is not None and unit_price < 0:
        return "negative_price"
    if quantity != quantity.to_integral_value():
        return "quantity_not_whole"
    return None


def _apply_line_issue_codes(line: ExtractedLine) -> None:
    line.issue_code = compute_line_issue_code(
        description=line.description.value,
        quantity=line.quantity.value,
        unit_price=line.unit_price.value,
        line_total=line.line_total.value,
    )


# --- Arithmetic validation (surfaces issues, never corrects) ------------

_TOLERANCE = Decimal("0.01")


def compute_header_issue_codes(
    *,
    subtotal: Decimal | None,
    tax_total: Decimal | None,
    discount_total: Decimal | None,
    shipping_total: Decimal | None,
    grand_total: Decimal | None,
    line_signatures: list[tuple],  # (description, quantity, unit_price) per non-excluded line
    line_totals: list[Decimal],  # only the ones that have a value at all
    line_count: int,
) -> list[str]:
    """Pure, plain-value version reused by both initial extraction
    (_validate_arithmetic below) and app/invoices/service.py's post-edit
    recompute (a header or line correction must re-run the same checks
    against the draft's current state, not only at extraction time)."""
    issues: list[str] = []
    if subtotal is not None and line_totals and len(line_totals) == line_count:
        if abs(sum(line_totals, Decimal("0")) - subtotal) > _TOLERANCE:
            issues.append("line_total_sum_mismatch_subtotal")

    if grand_total is not None and subtotal is not None:
        tax = tax_total or Decimal("0")
        discount = discount_total or Decimal("0")
        shipping = shipping_total or Decimal("0")
        expected = subtotal + tax - discount + shipping
        if abs(expected - grand_total) > _TOLERANCE:
            issues.append("grand_total_mismatch")

    seen_signatures: set[tuple] = set()
    for signature in line_signatures:
        if signature in seen_signatures and signature != (None, None, None):
            issues.append("duplicate_line_detected")
            break
        seen_signatures.add(signature)

    return issues


def _validate_arithmetic(header: dict[str, FieldProvenance], lines: list[ExtractedLine]) -> list[str]:
    return compute_header_issue_codes(
        subtotal=header["subtotal"].value,
        tax_total=header["tax_total"].value,
        discount_total=header["discount_total"].value,
        shipping_total=header["shipping_total"].value,
        grand_total=header["grand_total"].value,
        line_signatures=[(ln.description.value, ln.quantity.value, ln.unit_price.value) for ln in lines],
        line_totals=[ln.line_total.value for ln in lines if ln.line_total.value is not None],
        line_count=len(lines),
    )


def extract_invoice(pdf: PdfReadResult) -> ExtractedInvoice:
    all_lines: list[str] = []
    for page in pdf.pages:
        all_lines.extend(page.text.splitlines())
    all_text = "\n".join(all_lines)

    header, header_issues = _extract_header(all_lines, all_text)
    lines, line_extraction_issues = _extract_lines(pdf.pages)
    arithmetic_issues = _validate_arithmetic(header, lines)

    return ExtractedInvoice(
        supplier_name=header["supplier_name"],
        invoice_reference=header["invoice_reference"],
        invoice_date=header["invoice_date"],
        due_date=header["due_date"],
        currency=header["currency"],
        subtotal=header["subtotal"],
        tax_total=header["tax_total"],
        discount_total=header["discount_total"],
        shipping_total=header["shipping_total"],
        grand_total=header["grand_total"],
        lines=lines,
        header_issue_codes=[*header_issues, *line_extraction_issues, *arithmetic_issues],
    )
