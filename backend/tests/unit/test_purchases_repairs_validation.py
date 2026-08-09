from decimal import Decimal

from app.imports.importer import (
    ParsedPurchaseRow,
    ParsedRepairRow,
    RejectedRow,
    extract_mapped_values,
    validate_and_parse_purchase_row,
    validate_and_parse_repair_row,
)

_PURCHASE_COLUMNS = {"purchase_date": 0, "product_name": 1, "sku": 2, "quantity_received": 3, "unit_cost": 4}
_REPAIR_COLUMNS = {"repair_date": 0, "description": 1, "price_charged": 2, "labour_cost": 3}
_PURCHASE_COLUMNS_WITH_REF = {**_PURCHASE_COLUMNS, "purchase_reference": 5}
_PURCHASE_COLUMNS_WITH_SUPPLIER = {**_PURCHASE_COLUMNS, "supplier": 5}
_REPAIR_COLUMNS_WITH_REF = {**_REPAIR_COLUMNS, "repair_reference": 4}
_REPAIR_COLUMNS_WITH_TAX = {**_REPAIR_COLUMNS, "tax_amount": 4}


def _parse_purchase(row, columns=_PURCHASE_COLUMNS, row_number=1):
    return validate_and_parse_purchase_row(row_number, extract_mapped_values(row, columns))


def _parse_repair(row, columns=_REPAIR_COLUMNS, row_number=1):
    return validate_and_parse_repair_row(row_number, extract_mapped_values(row, columns))


# --- purchases ------------------------------------------------------------


def test_a_clean_purchase_row_parses_successfully():
    result = _parse_purchase(["2026-01-05", "Chain Lube", "CL-100", "50", "4.75"])
    assert isinstance(result, ParsedPurchaseRow)
    assert result.product_name == "Chain Lube"
    assert result.sku == "CL-100"
    assert result.quantity_received == 50
    assert result.unit_cost == Decimal("4.75")


def test_purchase_row_without_unit_cost_is_accepted():
    result = _parse_purchase(["2026-01-05", "Chain Lube", "CL-100", "50", ""])
    assert isinstance(result, ParsedPurchaseRow)
    assert result.unit_cost is None


def test_purchase_row_missing_date_is_rejected():
    result = _parse_purchase(["", "Chain Lube", "CL-100", "50", "4.75"])
    assert isinstance(result, RejectedRow)
    assert result.code == "missing_date"


def test_purchase_row_missing_both_identifiers_is_rejected():
    result = _parse_purchase(["2026-01-05", "", "", "50", "4.75"])
    assert isinstance(result, RejectedRow)
    assert result.code == "missing_product_identifier"


def test_purchase_row_sku_only_is_accepted():
    result = _parse_purchase(["2026-01-05", "", "CL-100", "50", "4.75"])
    assert isinstance(result, ParsedPurchaseRow)


def test_purchase_row_blank_or_unparseable_quantity_is_rejected():
    for qty_value in ("", "not a number"):
        result = _parse_purchase(["2026-01-05", "Chain Lube", "CL-100", qty_value, "4.75"])
        assert isinstance(result, RejectedRow)
        assert result.code == "missing_quantity"


def test_purchase_row_zero_or_negative_quantity_is_rejected_with_a_distinct_code():
    # Parses cleanly (unlike "missing_quantity") but is nonsensical for a
    # receipt — distinct code so the message doesn't wrongly claim it
    # "couldn't be read."
    for qty_value in ("0", "-5"):
        result = _parse_purchase(["2026-01-05", "Chain Lube", "CL-100", qty_value, "4.75"])
        assert isinstance(result, RejectedRow)
        assert result.code == "non_positive_quantity"


def test_purchase_row_without_a_reference_column_is_accepted():
    # No reference mapped at all — never a rejection reason on its own.
    result = _parse_purchase(["2026-01-05", "Chain Lube", "CL-100", "50", "4.75"])
    assert isinstance(result, ParsedPurchaseRow)
    assert result.reference is None


def test_purchase_row_reference_parses_when_mapped():
    result = _parse_purchase(
        ["2026-01-05", "Chain Lube", "CL-100", "50", "4.75", "PO-42"], columns=_PURCHASE_COLUMNS_WITH_REF
    )
    assert isinstance(result, ParsedPurchaseRow)
    assert result.reference == "PO-42"


def test_purchase_row_blank_reference_is_accepted_as_none():
    result = _parse_purchase(
        ["2026-01-05", "Chain Lube", "CL-100", "50", "4.75", ""], columns=_PURCHASE_COLUMNS_WITH_REF
    )
    assert isinstance(result, ParsedPurchaseRow)
    assert result.reference is None


def test_purchase_row_without_a_supplier_column_is_accepted():
    # Never a rejection reason on its own — "unknown supplier" is a
    # normal, expected state, same as no category mapped.
    result = _parse_purchase(["2026-01-05", "Chain Lube", "CL-100", "50", "4.75"])
    assert isinstance(result, ParsedPurchaseRow)
    assert result.supplier_name is None


def test_purchase_row_supplier_parses_when_mapped():
    result = _parse_purchase(
        ["2026-01-05", "Chain Lube", "CL-100", "50", "4.75", "Acme Parts Ltd"], columns=_PURCHASE_COLUMNS_WITH_SUPPLIER
    )
    assert isinstance(result, ParsedPurchaseRow)
    assert result.supplier_name == "Acme Parts Ltd"


def test_purchase_row_blank_supplier_is_accepted_as_none():
    result = _parse_purchase(
        ["2026-01-05", "Chain Lube", "CL-100", "50", "4.75", ""], columns=_PURCHASE_COLUMNS_WITH_SUPPLIER
    )
    assert isinstance(result, ParsedPurchaseRow)
    assert result.supplier_name is None


# --- repairs ----------------------------------------------------------


def test_a_clean_repair_row_parses_successfully():
    result = _parse_repair(["2026-01-05", "Replaced brake pads", "45.00", "20.00"])
    assert isinstance(result, ParsedRepairRow)
    assert result.description == "Replaced brake pads"
    assert result.price_charged == Decimal("45.00")
    assert result.labour_cost == Decimal("20.00")


def test_repair_row_missing_date_is_rejected():
    result = _parse_repair(["", "Replaced brake pads", "45.00", "20.00"])
    assert isinstance(result, RejectedRow)
    assert result.code == "missing_date"


def test_repair_row_description_only_is_accepted():
    result = _parse_repair(["2026-01-05", "Replaced brake pads", "", ""])
    assert isinstance(result, ParsedRepairRow)


def test_repair_row_price_only_is_accepted():
    result = _parse_repair(["2026-01-05", "", "45.00", ""])
    assert isinstance(result, ParsedRepairRow)


def test_repair_row_labour_cost_only_is_accepted():
    result = _parse_repair(["2026-01-05", "", "", "20.00"])
    assert isinstance(result, ParsedRepairRow)


def test_repair_row_with_no_detail_at_all_is_rejected():
    result = _parse_repair(["2026-01-05", "", "", ""])
    assert isinstance(result, RejectedRow)
    assert result.code == "missing_repair_detail"


def test_repair_row_without_a_reference_column_is_accepted():
    result = _parse_repair(["2026-01-05", "Replaced brake pads", "45.00", "20.00"])
    assert isinstance(result, ParsedRepairRow)
    assert result.reference is None


def test_repair_row_reference_parses_when_mapped():
    result = _parse_repair(
        ["2026-01-05", "Replaced brake pads", "45.00", "20.00", "JOB-9"], columns=_REPAIR_COLUMNS_WITH_REF
    )
    assert isinstance(result, ParsedRepairRow)
    assert result.reference == "JOB-9"


def test_repair_row_without_a_tax_column_is_accepted():
    # Never a rejection reason on its own, same as purchase/repair reference.
    result = _parse_repair(["2026-01-05", "Replaced brake pads", "45.00", "20.00"])
    assert isinstance(result, ParsedRepairRow)
    assert result.tax_amount is None


def test_repair_row_tax_amount_parses_when_mapped():
    result = _parse_repair(
        ["2026-01-05", "Replaced brake pads", "45.00", "20.00", "5.00"], columns=_REPAIR_COLUMNS_WITH_TAX
    )
    assert isinstance(result, ParsedRepairRow)
    assert result.tax_amount == Decimal("5.00")


def test_repair_row_blank_tax_amount_is_accepted_as_none():
    result = _parse_repair(
        ["2026-01-05", "Replaced brake pads", "45.00", "20.00", ""], columns=_REPAIR_COLUMNS_WITH_TAX
    )
    assert isinstance(result, ParsedRepairRow)
    assert result.tax_amount is None
