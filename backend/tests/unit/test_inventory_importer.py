import uuid
from decimal import Decimal

from app.imports.importer import (
    ParsedInventoryRow,
    RejectedRow,
    ResolvedInventoryRow,
    extract_mapped_values,
    reconcile_inventory_rows,
    validate_and_parse_inventory_row,
)

_COLUMNS = {"product_name": 0, "sku": 1, "quantity_on_hand": 2}
_COLUMNS_WITH_COST = {"product_name": 0, "sku": 1, "quantity_on_hand": 2, "unit_cost": 3}


def _parse(row, columns=_COLUMNS, row_number=1):
    return validate_and_parse_inventory_row(row_number, extract_mapped_values(row, columns))


def test_a_clean_row_parses_successfully():
    result = _parse(["Chain Lube", "CL-100", "25"])
    assert isinstance(result, ParsedInventoryRow)
    assert result.product_name == "Chain Lube"
    assert result.sku == "CL-100"
    assert result.quantity_on_hand == 25
    assert result.unit_cost is None  # not mapped in this file at all


def test_a_row_with_unit_cost_parses_it():
    result = _parse(["Chain Lube", "CL-100", "25", "3.50"], columns=_COLUMNS_WITH_COST)
    assert isinstance(result, ParsedInventoryRow)
    assert result.unit_cost == Decimal("3.50")


def test_inventory_row_without_unit_cost_is_accepted():
    # unit_cost mapped to a column, but blank on this particular row —
    # optional, like purchases' unit_cost, never a rejection reason.
    result = _parse(["Chain Lube", "CL-100", "25", ""], columns=_COLUMNS_WITH_COST)
    assert isinstance(result, ParsedInventoryRow)
    assert result.unit_cost is None


def test_sku_only_row_is_accepted():
    result = _parse(["", "CL-100", "25"])
    assert isinstance(result, ParsedInventoryRow)


def test_name_only_row_is_accepted():
    result = _parse(["Chain Lube", "", "25"])
    assert isinstance(result, ParsedInventoryRow)


def test_missing_both_identifiers_is_rejected():
    result = _parse(["", "", "25"])
    assert isinstance(result, RejectedRow)
    assert result.code == "missing_product_identifier"


def test_blank_or_unparseable_quantity_is_rejected_never_defaulted():
    for qty_value in ("", "not a number"):
        result = _parse(["Chain Lube", "CL-100", qty_value])
        assert isinstance(result, RejectedRow)
        assert result.code == "missing_quantity"


def test_negative_quantity_is_rejected():
    result = _parse(["Chain Lube", "CL-100", "-5"])
    assert isinstance(result, RejectedRow)
    assert result.code == "negative_quantity"


def test_zero_quantity_is_accepted():
    result = _parse(["Chain Lube", "CL-100", "0"])
    assert isinstance(result, ParsedInventoryRow)
    assert result.quantity_on_hand == 0


# --- reconcile_inventory_rows (pure) -------------------------------------

_P1, _P2 = uuid.uuid4(), uuid.uuid4()


def test_delta_is_computed_against_starting_stock():
    rows = [ResolvedInventoryRow(1, _P1, quantity_on_hand=20, is_new_product=False)]
    results, duplicates = reconcile_inventory_rows(rows, {_P1: 12})
    assert results[0].delta == 8
    assert duplicates == []


def test_new_product_starts_from_zero_stock_regardless_of_the_dict():
    # starting_stock has a stale/irrelevant entry for _P1 — is_new_product
    # must force the baseline to 0, not consult the dict at all.
    rows = [ResolvedInventoryRow(1, _P1, quantity_on_hand=20, is_new_product=True)]
    results, _ = reconcile_inventory_rows(rows, {_P1: 999})
    assert results[0].delta == 20


def test_zero_delta_row_is_still_a_result_with_delta_zero():
    rows = [ResolvedInventoryRow(1, _P1, quantity_on_hand=12, is_new_product=False)]
    results, _ = reconcile_inventory_rows(rows, {_P1: 12})
    assert results[0].delta == 0


def test_duplicate_product_in_file_compounds_correctly_not_against_stale_snapshot():
    # Same product twice in one file, both claiming qty=15. A read-only
    # starting-stock snapshot would compute +5 twice (wrong, final=20);
    # the running total must compound: +5 then 0 (final=15, correct).
    rows = [
        ResolvedInventoryRow(1, _P1, quantity_on_hand=15, is_new_product=False),
        ResolvedInventoryRow(2, _P1, quantity_on_hand=15, is_new_product=False),
    ]
    results, duplicates = reconcile_inventory_rows(rows, {_P1: 10})
    assert [r.delta for r in results] == [5, 0]
    assert duplicates == [{"row_number": 2}]


def test_unrelated_products_do_not_trigger_a_duplicate_warning():
    rows = [
        ResolvedInventoryRow(1, _P1, quantity_on_hand=15, is_new_product=False),
        ResolvedInventoryRow(2, _P2, quantity_on_hand=8, is_new_product=False),
    ]
    _, duplicates = reconcile_inventory_rows(rows, {_P1: 10, _P2: 8})
    assert duplicates == []


def test_starting_stock_dict_passed_in_is_never_mutated():
    starting = {_P1: 10}
    rows = [ResolvedInventoryRow(1, _P1, quantity_on_hand=15, is_new_product=False)]
    reconcile_inventory_rows(rows, starting)
    assert starting == {_P1: 10}
