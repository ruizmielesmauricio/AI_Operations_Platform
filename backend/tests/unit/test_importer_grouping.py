from datetime import date
from decimal import Decimal

from app.imports.importer import (
    ParsedSaleRow,
    ProductMatcher,
    group_rows_into_sales,
    group_sold_at,
    group_total_amount,
    normalize_product_name,
    normalize_sku,
)


def _row(row_number, order_reference=None, sale_date=date(2026, 1, 1), unit_price="5.00", quantity=1):
    return ParsedSaleRow(
        row_number=row_number,
        sale_date=sale_date,
        product_name="Widget",
        sku=None,
        quantity=quantity,
        unit_price=Decimal(unit_price),
        cost_price_at_sale=None,
        order_reference=order_reference,
    )


def test_rows_sharing_an_order_reference_are_grouped():
    rows = [_row(1, "ORD-1"), _row(2, "ORD-1"), _row(3, "ORD-2")]
    groups = group_rows_into_sales(rows)
    assert [[r.row_number for r in g] for g in groups] == [[1, 2], [3]]


def test_blank_order_reference_rows_are_never_grouped_together():
    rows = [_row(1, None), _row(2, ""), _row(3, "   ")]
    groups = group_rows_into_sales(rows)
    assert len(groups) == 3  # each its own singleton, not merged


def test_order_reference_whitespace_is_collapsed_but_case_preserved():
    rows = [_row(1, "  ord-1  "), _row(2, "ord-1")]
    groups = group_rows_into_sales(rows)
    assert len(groups) == 1  # same after whitespace collapse

    rows_diff_case = [_row(1, "ORD-1"), _row(2, "ord-1")]
    groups_diff_case = group_rows_into_sales(rows_diff_case)
    assert len(groups_diff_case) == 2  # case-sensitive: order ids often are


def test_group_total_amount_sums_price_times_quantity():
    rows = [_row(1, "ORD-1", unit_price="5.00", quantity=2), _row(2, "ORD-1", unit_price="7.00", quantity=1)]
    assert group_total_amount(rows) == Decimal("17.00")


def test_group_sold_at_is_the_earliest_date_in_the_group():
    rows = [
        _row(1, "ORD-1", sale_date=date(2026, 1, 5)),
        _row(2, "ORD-1", sale_date=date(2026, 1, 3)),
    ]
    assert group_sold_at(rows) == date(2026, 1, 3)


def test_normalize_sku_is_case_and_whitespace_insensitive_but_keeps_hyphens():
    assert normalize_sku(" cl-100 ") == normalize_sku("CL-100") == "CL-100"


def test_normalize_product_name_is_case_and_whitespace_insensitive():
    assert normalize_product_name("  Chain   Lube ") == normalize_product_name("chain lube") == "chain lube"


class _FakeProduct:
    def __init__(self, id, sku, name):
        self.id = id
        self.sku = sku
        self.name = name


def test_sku_match_wins_even_with_a_different_row_supplied_name():
    matcher = ProductMatcher([_FakeProduct("p1", "CL-100", "Chain Lube")])
    match = matcher.resolve(sku="cl-100", product_name="Chain Lube 100ml")
    assert match.action == "existing"
    assert match.product_id == "p1"
    assert match.name_mismatch is True


def test_unknown_sku_creates_a_new_product_even_if_name_matches_another_product():
    # Deliberately no fallback to name matching when SKU is present but
    # unmatched — trusting the name guess risks merging two distinct
    # products' sales history.
    matcher = ProductMatcher([_FakeProduct("p1", "CL-100", "Chain Lube")])
    match = matcher.resolve(sku="CL-999", product_name="Chain Lube")
    assert match.action == "create"
    assert match.create_sku == "CL-999"


def test_name_only_match_when_sku_is_blank():
    matcher = ProductMatcher([_FakeProduct("p1", None, "Chain Lube")])
    match = matcher.resolve(sku=None, product_name="chain lube")
    assert match.action == "existing"
    assert match.product_id == "p1"


def test_both_blank_resolves_to_none_not_a_creation():
    matcher = ProductMatcher([])
    match = matcher.resolve(sku=None, product_name=None)
    assert match.action == "none"


def test_registered_product_resolves_on_a_later_row_in_the_same_file():
    matcher = ProductMatcher([])
    first = matcher.resolve(sku="BT-200", product_name="Bar Tape")
    assert first.action == "create"
    matcher.register_created(_FakeProduct("new-id", "BT-200", "Bar Tape"))
    second = matcher.resolve(sku="bt-200", product_name="Bar Tape")
    assert second.action == "existing"
    assert second.product_id == "new-id"
