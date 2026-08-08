"""Covers app/analytics/category.py::compute_category_breakdown — pure,
no DB. Mirrors this codebase's convention of hand-built fixtures over the
shared dataclasses (see tests/unit/test_financial_analytics.py/
test_retail_analytics.py)."""

import uuid
from decimal import Decimal

from app.analytics.category import compute_category_breakdown
from app.analytics.types import ProductPeriodAggregate, ProductPurchaseCostAggregate

_CAT_A = uuid.uuid4()
_CAT_B = uuid.uuid4()
_PRODUCT_A1 = uuid.uuid4()
_PRODUCT_A2 = uuid.uuid4()
_PRODUCT_B1 = uuid.uuid4()
_PRODUCT_UNCATEGORIZED = uuid.uuid4()


def _revenue_aggregate(product_id, revenue) -> ProductPeriodAggregate:
    return ProductPeriodAggregate(
        product_id=product_id, units_sold=1, revenue=Decimal(revenue),
        revenue_with_known_cost=Decimal(revenue), cogs=Decimal("0"),
    )


def _purchase_aggregate(product_id, qty, qty_known, cost) -> ProductPurchaseCostAggregate:
    return ProductPurchaseCostAggregate(
        product_id=product_id, quantity_received=qty, quantity_received_with_known_cost=qty_known, cost=Decimal(cost)
    )


_CATEGORY_NAME_BY_ID = {_CAT_A: "Parts", _CAT_B: "Accessories"}
_CATEGORY_ID_BY_PRODUCT = {
    _PRODUCT_A1: _CAT_A,
    _PRODUCT_A2: _CAT_A,
    _PRODUCT_B1: _CAT_B,
    _PRODUCT_UNCATEGORIZED: None,
}


def test_revenue_and_expenses_sum_per_category():
    revenue_aggs = [_revenue_aggregate(_PRODUCT_A1, "100.00"), _revenue_aggregate(_PRODUCT_A2, "50.00")]
    purchase_aggs = [_purchase_aggregate(_PRODUCT_A1, 10, 10, "40.00")]
    rows = compute_category_breakdown(
        revenue_aggs, purchase_aggs, {}, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, {}
    )
    parts_row = next(r for r in rows if r.category_id == _CAT_A)
    assert parts_row.category_name == "Parts"
    assert parts_row.revenue == Decimal("150.00")
    assert parts_row.expenses == Decimal("40.00")


def test_products_with_no_category_land_in_uncategorized_bucket():
    revenue_aggs = [_revenue_aggregate(_PRODUCT_UNCATEGORIZED, "20.00")]
    rows = compute_category_breakdown(revenue_aggs, [], {}, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, {})
    uncategorized = next(r for r in rows if r.category_id is None)
    assert uncategorized.category_name == "Uncategorized"
    assert uncategorized.revenue == Decimal("20.00")


def test_a_category_with_only_purchases_and_no_sales_still_appears():
    purchase_aggs = [_purchase_aggregate(_PRODUCT_B1, 5, 5, "25.00")]
    rows = compute_category_breakdown([], purchase_aggs, {}, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, {})
    accessories_row = next(r for r in rows if r.category_id == _CAT_B)
    assert accessories_row.revenue == Decimal("0.00")
    assert accessories_row.expenses == Decimal("25.00")


def test_expenses_data_coverage_pct_reflects_known_vs_total_purchased_quantity():
    # 10 units received, only 4 have a known unit_cost.
    purchase_aggs = [_purchase_aggregate(_PRODUCT_A1, 10, 4, "16.00")]
    rows = compute_category_breakdown([], purchase_aggs, {}, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, {})
    parts_row = next(r for r in rows if r.category_id == _CAT_A)
    assert parts_row.expenses_data_coverage_pct == Decimal("40.0")


def test_expenses_data_coverage_pct_is_none_when_no_purchase_quantity_in_period():
    revenue_aggs = [_revenue_aggregate(_PRODUCT_A1, "10.00")]
    rows = compute_category_breakdown(revenue_aggs, [], {}, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, {})
    parts_row = next(r for r in rows if r.category_id == _CAT_A)
    assert parts_row.expenses_data_coverage_pct is None


def test_stock_value_uses_sell_price_not_cost_price():
    stock_on_hand = {_PRODUCT_A1: 10}
    sell_price_by_product = {_PRODUCT_A1: Decimal("9.99")}
    rows = compute_category_breakdown(
        [], [], stock_on_hand, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, sell_price_by_product
    )
    parts_row = next(r for r in rows if r.category_id == _CAT_A)
    assert parts_row.stock_value == Decimal("99.90")


def test_products_missing_sell_price_are_excluded_from_stock_value_not_treated_as_zero():
    stock_on_hand = {_PRODUCT_A1: 10, _PRODUCT_A2: 5}
    sell_price_by_product = {_PRODUCT_A1: Decimal("10.00")}  # A2 has no sell price
    rows = compute_category_breakdown(
        [], [], stock_on_hand, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, sell_price_by_product
    )
    parts_row = next(r for r in rows if r.category_id == _CAT_A)
    assert parts_row.stock_value == Decimal("100.00")
    assert parts_row.products_excluded_from_stock_value == 1


def test_zero_stock_products_are_never_counted_or_excluded_from_stock_value():
    stock_on_hand = {_PRODUCT_A1: 0}
    rows = compute_category_breakdown([], [], stock_on_hand, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, {})
    parts_row = next(r for r in rows if r.category_id == _CAT_A)
    assert parts_row.stock_value == Decimal("0.00")
    assert parts_row.products_excluded_from_stock_value == 0


def test_rows_are_sorted_by_revenue_descending():
    revenue_aggs = [_revenue_aggregate(_PRODUCT_B1, "5.00"), _revenue_aggregate(_PRODUCT_A1, "500.00")]
    rows = compute_category_breakdown(revenue_aggs, [], {}, _CATEGORY_ID_BY_PRODUCT, _CATEGORY_NAME_BY_ID, {})
    assert [r.category_id for r in rows] == [_CAT_A, _CAT_B]


def test_unknown_category_id_falls_back_to_uncategorized_name():
    # A product whose category_id points at a category that isn't in
    # category_name_by_id (e.g. deleted, or an id typo) — fails closed to
    # "Uncategorized" rather than crashing or showing a blank name.
    stray_category_id = uuid.uuid4()
    revenue_aggs = [_revenue_aggregate(_PRODUCT_A1, "10.00")]
    rows = compute_category_breakdown(
        revenue_aggs, [], {}, {_PRODUCT_A1: stray_category_id}, {}, {}
    )
    assert rows[0].category_name == "Uncategorized"
