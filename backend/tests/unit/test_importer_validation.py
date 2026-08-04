from decimal import Decimal

from app.imports.importer import (
    ParsedSaleRow,
    RejectedRow,
    extract_mapped_values,
    validate_and_parse_row,
)

_COLUMNS = {"sale_date": 0, "product_name": 1, "sku": 2, "quantity": 3, "unit_price": 4}


def _parse(row, columns=_COLUMNS, row_number=1):
    return validate_and_parse_row(row_number, extract_mapped_values(row, columns))


def test_a_clean_row_parses_successfully():
    result = _parse(["2026-01-03", "Chain Lube", "CL-100", "3", "9.99"])
    assert isinstance(result, ParsedSaleRow)
    assert result.sale_date.isoformat() == "2026-01-03"
    assert result.quantity == 3
    assert result.unit_price == Decimal("9.99")
    assert result.total_amount_mismatch is False


def test_blank_or_unparseable_date_is_rejected():
    for date_value in ("", "not a date"):
        result = _parse([date_value, "Chain Lube", "CL-100", "3", "9.99"])
        assert isinstance(result, RejectedRow)
        assert result.code == "missing_date"


def test_no_usable_price_is_rejected():
    columns = {"sale_date": 0, "quantity": 1}
    result = validate_and_parse_row(1, extract_mapped_values(["2026-01-03", "3"], columns))
    assert isinstance(result, RejectedRow)
    assert result.code == "missing_price"


def test_present_but_garbled_quantity_is_rejected():
    result = _parse(["2026-01-03", "Chain Lube", "CL-100", "not a number", "9.99"])
    assert isinstance(result, RejectedRow)
    assert result.code == "invalid_quantity"


def test_blank_quantity_defaults_to_one_not_rejected():
    result = _parse(["2026-01-03", "Chain Lube", "CL-100", "", "9.99"])
    assert isinstance(result, ParsedSaleRow)
    assert result.quantity == 1


def test_unmapped_quantity_defaults_to_one():
    columns = {"sale_date": 0, "unit_price": 1}
    result = validate_and_parse_row(1, extract_mapped_values(["2026-01-03", "9.99"], columns))
    assert isinstance(result, ParsedSaleRow)
    assert result.quantity == 1


def test_unit_price_derived_from_total_amount_when_unit_price_not_mapped():
    columns = {"sale_date": 0, "total_amount": 1, "quantity": 2}
    result = validate_and_parse_row(1, extract_mapped_values(["2026-01-03", "30.00", "3"], columns))
    assert isinstance(result, ParsedSaleRow)
    assert result.unit_price == Decimal("10.00")


def test_matching_total_amount_does_not_flag_a_mismatch():
    columns = {"sale_date": 0, "unit_price": 1, "quantity": 2, "total_amount": 3}
    result = validate_and_parse_row(1, extract_mapped_values(["2026-01-03", "9.99", "3", "29.97"], columns))
    assert isinstance(result, ParsedSaleRow)
    assert result.total_amount_mismatch is False


def test_mismatched_total_amount_is_flagged_but_not_rejected():
    columns = {"sale_date": 0, "unit_price": 1, "quantity": 2, "total_amount": 3}
    result = validate_and_parse_row(1, extract_mapped_values(["2026-01-03", "9.99", "3", "50.00"], columns))
    assert isinstance(result, ParsedSaleRow)  # not rejected — a warning, not a failure
    assert result.total_amount_mismatch is True


def test_garbled_cost_price_is_never_a_rejection():
    columns = dict(_COLUMNS, cost_price_at_sale=5)
    result = validate_and_parse_row(
        1, extract_mapped_values(["2026-01-03", "Chain Lube", "CL-100", "3", "9.99", "not a price"], columns)
    )
    assert isinstance(result, ParsedSaleRow)
    assert result.cost_price_at_sale is None


def test_rejected_row_carries_display_values_of_every_mapped_field():
    result = _parse(["", "Chain Lube", "CL-100", "3", "9.99"])
    assert isinstance(result, RejectedRow)
    assert result.raw == {
        "sale_date": "",
        "product_name": "Chain Lube",
        "sku": "CL-100",
        "quantity": "3",
        "unit_price": "9.99",
    }
