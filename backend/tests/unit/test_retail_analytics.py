import uuid
from decimal import Decimal

from app.analytics.retail import (
    build_stock_cover_report,
    compute_inventory_value_at_cost,
    compute_sell_through_rate,
    compute_stock_cover_days,
    find_dead_stock,
    rank_top_sellers_by_revenue,
    rank_top_sellers_by_units,
)
from app.analytics.types import ProductPeriodAggregate

_P1, _P2, _P3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _aggregate(product_id, *, units_sold, revenue="0"):
    return ProductPeriodAggregate(
        product_id=product_id,
        units_sold=units_sold,
        revenue=Decimal(revenue),
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
    cost_price_by_product = {_P1: Decimal("5.00"), _P3: None}

    dead_stock = find_dead_stock(aggregates_by_product, stock_by_product, products_by_id, cost_price_by_product)
    by_id = {entry.product_id: entry for entry in dead_stock}

    assert set(by_id) == {_P1, _P3}
    assert all(entry.stock_on_hand > 0 for entry in dead_stock)
    assert by_id[_P1].value_at_cost == Decimal("100.00")  # 20 * 5.00
    assert by_id[_P3].value_at_cost is None  # no cost_price on record


def test_find_dead_stock_excludes_products_with_no_stock():
    aggregates_by_product: dict = {}
    stock_by_product = {_P1: 0}
    products_by_id = {_P1: "Empty Shelf"}

    assert find_dead_stock(aggregates_by_product, stock_by_product, products_by_id, {}) == []


def test_rank_top_sellers_by_units_favours_volume_over_price():
    # A cheap item selling in volume must outrank an expensive item that
    # barely sold, even though the expensive one made more revenue — this
    # is the exact case the units/revenue split exists to fix.
    aggregates = [
        _aggregate(_P1, units_sold=3, revenue="1500.00"),  # expensive, low volume
        _aggregate(_P2, units_sold=300, revenue="900.00"),  # cheap, high volume
    ]
    products_by_id = {_P1: "Premium Bike", _P2: "Puncture Kit"}

    ranked = rank_top_sellers_by_units(aggregates, products_by_id, top_n=5)

    assert [row.product_id for row in ranked] == [_P2, _P1]


def test_rank_top_sellers_by_revenue_favours_price_over_volume():
    aggregates = [
        _aggregate(_P1, units_sold=3, revenue="1500.00"),
        _aggregate(_P2, units_sold=300, revenue="900.00"),
    ]
    products_by_id = {_P1: "Premium Bike", _P2: "Puncture Kit"}

    ranked = rank_top_sellers_by_revenue(aggregates, products_by_id, top_n=5)

    assert [row.product_id for row in ranked] == [_P1, _P2]


def test_rank_top_sellers_respects_top_n():
    aggregates = [_aggregate(uuid.uuid4(), units_sold=i, revenue=str(i)) for i in range(1, 8)]
    products_by_id = {a.product_id: f"Product {a.units_sold}" for a in aggregates}

    assert len(rank_top_sellers_by_units(aggregates, products_by_id, top_n=3)) == 3
    assert len(rank_top_sellers_by_revenue(aggregates, products_by_id, top_n=3)) == 3


def test_build_stock_cover_report_carries_each_products_period_revenue():
    aggregates_by_product = {_P1: _aggregate(_P1, units_sold=10, revenue="150.00")}
    stock_by_product = {_P1: 40, _P2: 5}  # P2 has no aggregate row (no sales in the period)
    products_by_id = {_P1: "Chain Lube", _P2: "Bar Tape"}

    rows = {row.product_id: row for row in build_stock_cover_report(aggregates_by_product, stock_by_product, products_by_id, 30)}

    assert rows[_P1].revenue_in_period == Decimal("150.00")
    assert rows[_P2].revenue_in_period == Decimal("0.00")


def test_inventory_value_at_cost_sums_stock_times_cost_and_flags_missing_cost():
    stock_by_product = {_P1: 10, _P2: 5, _P3: 0}
    cost_price_by_product = {_P1: Decimal("20.00"), _P2: None, _P3: Decimal("5.00")}

    result = compute_inventory_value_at_cost(stock_by_product, cost_price_by_product)

    assert result.value_at_cost == Decimal("200.00")  # only P1: 10 * 20.00; P3 excluded (0 stock)
    assert result.products_missing_cost == 1  # P2 has stock but no cost_price
