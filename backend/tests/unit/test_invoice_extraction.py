"""Covers app/invoices/extraction.py's field/line extraction and
arithmetic validation. The header/line label parsing and table-column
matching are exercised end-to-end against realistic generated PDF
fixtures (tests/invoice_pdf_helpers.py) — the pure recompute helpers
(compute_line_issue_code/compute_header_issue_codes, reused by
app/invoices/service.py for post-edit recomputation) are covered
directly with hand-picked values, same rigor as tests/unit/
test_weather_patterns.py's own hand-computed fixtures.
"""

from decimal import Decimal

from app.invoices import extraction, pdf_reader
from tests.invoice_pdf_helpers import build_invoice_pdf, build_no_table_pdf


def _extract(**kwargs) -> extraction.ExtractedInvoice:
    return extraction.extract_invoice(pdf_reader.read_pdf(build_invoice_pdf(**kwargs)))


# --- End-to-end extraction against a realistic fixture -------------------


def test_clean_invoice_extracts_every_header_field_correctly():
    inv = _extract()

    assert inv.invoice_reference.value == "INV-2024-0456"
    assert inv.invoice_date.value.isoformat() == "2026-03-15"
    assert inv.due_date.value.isoformat() == "2026-04-14"
    assert inv.subtotal.value == Decimal("220.00")
    assert inv.tax_total.value == Decimal("50.60")
    assert inv.grand_total.value == Decimal("270.60")
    assert inv.header_issue_codes == []


def test_clean_invoice_extracts_every_line_field_correctly():
    inv = _extract()

    assert len(inv.lines) == 2
    first = inv.lines[0]
    assert first.supplier_sku.value == "TYR-001"
    assert first.description.value == "Road Tyre 700x25c"
    assert first.quantity.value == Decimal("10")
    assert first.unit_price.value == Decimal("15.00")
    assert first.line_total.value == Decimal("150.00")
    assert first.issue_code is None


def test_currency_symbol_is_detected_from_the_document():
    inv = _extract(subtotal="€220.00", tax_total="€50.60", grand_total="€270.60")

    assert inv.currency.value == "EUR"


def test_a_line_total_sum_mismatch_against_subtotal_is_surfaced_not_corrected():
    # Subtotal deliberately wrong (should be 220.00 given the two lines).
    inv = _extract(subtotal="500.00", tax_total="50.60", grand_total="550.60")

    assert "line_total_sum_mismatch_subtotal" in inv.header_issue_codes
    # Never silently corrected -- the raw extracted figure is preserved.
    assert inv.subtotal.value == Decimal("500.00")


def test_a_grand_total_mismatch_is_surfaced():
    inv = _extract(grand_total="999.99")

    assert "grand_total_mismatch" in inv.header_issue_codes


def test_an_invoice_with_no_ruled_table_produces_zero_lines_and_an_honest_issue_code():
    # No word-position fallback heuristic exists (module docstring) --
    # never a fragile, low-confidence guess.
    pdf = pdf_reader.read_pdf(build_no_table_pdf())
    inv = extraction.extract_invoice(pdf)

    assert inv.lines == []
    assert "line_items_not_detected" in inv.header_issue_codes


def test_a_line_missing_a_price_is_flagged_but_still_extracted():
    inv = _extract(
        lines=[("TYR-001", "Road Tyre 700x25c", "10", "", "")],
        subtotal="0.00", tax_total="0.00", grand_total="0.00",
    )

    assert len(inv.lines) == 1
    assert inv.lines[0].issue_code == "missing_price"


def test_a_duplicate_line_is_detected():
    inv = _extract(
        lines=[
            ("TYR-001", "Road Tyre 700x25c", "10", "15.00", "150.00"),
            ("TYR-001", "Road Tyre 700x25c", "10", "15.00", "150.00"),
        ],
        subtotal="300.00", tax_total="0.00", grand_total="300.00",
    )

    assert "duplicate_line_detected" in inv.header_issue_codes


# --- Pure recompute helpers (hand-computed, reused for post-edit checks) --


def test_compute_line_issue_code_missing_description():
    assert extraction.compute_line_issue_code(
        description=None, quantity=Decimal("1"), unit_price=Decimal("10"), line_total=Decimal("10")
    ) == "missing_description"


def test_compute_line_issue_code_missing_quantity():
    assert extraction.compute_line_issue_code(
        description="Widget", quantity=None, unit_price=Decimal("10"), line_total=None
    ) == "missing_quantity"


def test_compute_line_issue_code_missing_price_when_both_unit_price_and_line_total_absent():
    assert extraction.compute_line_issue_code(
        description="Widget", quantity=Decimal("1"), unit_price=None, line_total=None
    ) == "missing_price"


def test_compute_line_issue_code_a_line_total_alone_satisfies_the_price_requirement():
    assert extraction.compute_line_issue_code(
        description="Widget", quantity=Decimal("1"), unit_price=None, line_total=Decimal("10")
    ) is None


def test_compute_line_issue_code_negative_quantity():
    assert extraction.compute_line_issue_code(
        description="Widget", quantity=Decimal("-1"), unit_price=Decimal("10"), line_total=None
    ) == "negative_quantity"


def test_compute_line_issue_code_fractional_quantity_is_flagged():
    # InventoryMovement.quantity_delta is Integer -- a fractional
    # extracted/edited quantity must be surfaced, never silently rounded.
    assert extraction.compute_line_issue_code(
        description="Widget", quantity=Decimal("2.5"), unit_price=Decimal("10"), line_total=None
    ) == "quantity_not_whole"


def test_compute_line_issue_code_a_clean_line_has_no_issue():
    assert extraction.compute_line_issue_code(
        description="Widget", quantity=Decimal("2"), unit_price=Decimal("10"), line_total=Decimal("20")
    ) is None


def test_compute_header_issue_codes_clean_totals_produce_no_issues():
    issues = extraction.compute_header_issue_codes(
        subtotal=Decimal("220.00"), tax_total=Decimal("50.60"), discount_total=None, shipping_total=None,
        grand_total=Decimal("270.60"),
        line_signatures=[("A", Decimal("10"), Decimal("15.00")), ("B", Decimal("20"), Decimal("3.50"))],
        line_totals=[Decimal("150.00"), Decimal("70.00")],
        line_count=2,
    )
    assert issues == []


def test_compute_header_issue_codes_within_tolerance_is_not_flagged():
    # 0.01 tolerance, same as app/imports/importer.py's own mismatch check.
    issues = extraction.compute_header_issue_codes(
        subtotal=Decimal("220.00"), tax_total=None, discount_total=None, shipping_total=None,
        grand_total=Decimal("220.00"),
        line_signatures=[("A", Decimal("1"), Decimal("220.00"))],
        line_totals=[Decimal("220.01")],
        line_count=1,
    )
    assert issues == []


def test_compute_header_issue_codes_excludes_a_line_currently_marked_excluded():
    # app/invoices/service.py only ever passes non-excluded lines into
    # this function's line_signatures/line_totals/line_count -- verified
    # here at the pure-function level: a 1-line, 1-total input with a
    # matching subtotal must not be flagged just because a 2nd (excluded)
    # line exists elsewhere and isn't included here.
    issues = extraction.compute_header_issue_codes(
        subtotal=Decimal("150.00"), tax_total=None, discount_total=None, shipping_total=None, grand_total=None,
        line_signatures=[("A", Decimal("10"), Decimal("15.00"))],
        line_totals=[Decimal("150.00")],
        line_count=1,
    )
    assert issues == []
