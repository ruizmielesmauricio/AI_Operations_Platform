import uuid
from decimal import Decimal

from app.analytics.retail import (
    compute_inventory_value_at_cost,
    compute_sell_through_rate,
    compute_stock_cover_days,
    find_dead_stock,
)
from app.analytics.types import ProductPeriodAggregate

_P1, _P2, _P3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _aggregate(product_id, *, units_sold):
    return ProductPeriodAggregate(
        product_id=product_id,
        units_sold=units_sold,
        revenue=Decimal("0"),
        revenue_with_known_cost=Decimal("0"),
        cogs=Decimal("0"),
    )


def test_stock_cover_days_projects_from_average_daily_sales_rate():
    # 30 units in stock, sold 15 over a 30-day period -> 0.5/day -> 60 days cover
    assert compute_stock_cover_days(30, 15, 30) == Decimal("60.00")


def test_stock_cover_days_is_zero_when_out_of_stock_regardless_of_sales_rate():
    assert compute_stock_cover_days(0, 100, 30) == Decimal("0")


def test_stock_cover_days_is_unknown_with_no_recent_sales():
    # Stock on hand but nothing sold in the period — no depletion rate to
    # project from. Must not be reported as "infinite" or "0".
    assert compute_stock_cover_days(50, 0, 30) is None


def test_sell_through_rate():
    assert compute_sell_through_rate(units_sold_in_period=30, stock_on_hand=10) == Decimal("0.750")


def test_sell_through_rate_is_none_with_no_stock_and_no_sales():
    assert compute_sell_through_rate(units_sold_in_period=0, stock_on_hand=0) is None


def test_find_dead_stock_flags_products_with_stock_and_no_sales():
    aggregates_by_product = {_P1: _aggregate(_P1, units_sold=0), _P2: _aggregate(_P2, units_sold=5)}
    stock_by_product = {_P1: 20, _P2: 20, _P3: 10}  # P3 never sold, no aggregate row at all
    products_by_id = {_P1: "Old Stock", _P2: "Fast Mover", _P3: "Never Sold"}

    dead_stock = find_dead_stock(aggregates_by_product, stock_by_product, products_by_id)

    assert {entry.product_id for entry in dead_stock} == {_P1, _P3}
    assert all(entry.stock_on_hand > 0 for entry in dead_stock)


def test_find_dead_stock_excludes_products_with_no_stock():
    aggregates_by_product: dict = {}
    stock_by_product = {_P1: 0}
    products_by_id = {_P1: "Empty Shelf"}

    assert find_dead_stock(aggregates_by_product, stock_by_product, products_by_id) == []


def test_inventory_value_at_cost_sums_stock_times_cost_and_flags_missing_cost():
    stock_by_product = {_P1: 10, _P2: 5, _P3: 0}
    cost_price_by_product = {_P1: Decimal("20.00"), _P2: None, _P3: Decimal("5.00")}

    result = compute_inventory_value_at_cost(stock_by_product, cost_price_by_product)

    assert result.value_at_cost == Decimal("200.00")  # only P1: 10 * 20.00; P3 excluded (0 stock)
    assert result.products_missing_cost == 1  # P2 has stock but no cost_price
