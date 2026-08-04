import uuid
from decimal import Decimal

from app.analytics.financial import compute_gross_margin, compute_revenue_change, rank_products_by_margin
from app.analytics.types import ProductPeriodAggregate

_P1, _P2, _P3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _aggregate(product_id, *, units_sold, revenue, revenue_with_known_cost, cogs):
    return ProductPeriodAggregate(
        product_id=product_id,
        units_sold=units_sold,
        revenue=Decimal(revenue),
        revenue_with_known_cost=Decimal(revenue_with_known_cost),
        cogs=Decimal(cogs),
    )


def test_gross_margin_with_full_cost_coverage():
    aggregates = [
        _aggregate(_P1, units_sold=10, revenue="1000.00", revenue_with_known_cost="1000.00", cogs="600.00"),
        _aggregate(_P2, units_sold=5, revenue="500.00", revenue_with_known_cost="500.00", cogs="200.00"),
    ]
    result = compute_gross_margin(aggregates)

    assert result.total_revenue == Decimal("1500.00")
    assert result.revenue_with_known_cost == Decimal("1500.00")
    assert result.cogs == Decimal("800.00")
    assert result.gross_profit == Decimal("700.00")
    assert result.gross_margin_pct == Decimal("46.7")  # 700/1500
    assert result.cost_data_coverage_pct == Decimal("100.0")


def test_gross_margin_flags_partial_cost_data_coverage():
    aggregates = [
        _aggregate(_P1, units_sold=10, revenue="1000.00", revenue_with_known_cost="1000.00", cogs="600.00"),
        # No cost data for this product's line items — contributes to
        # revenue but not to margin.
        _aggregate(_P2, units_sold=5, revenue="500.00", revenue_with_known_cost="0", cogs="0"),
    ]
    result = compute_gross_margin(aggregates)

    assert result.total_revenue == Decimal("1500.00")
    assert result.revenue_with_known_cost == Decimal("1000.00")
    assert result.gross_profit == Decimal("400.00")
    assert result.gross_margin_pct == Decimal("40.0")
    # 1000 known out of 1500 total revenue
    assert result.cost_data_coverage_pct == Decimal("66.7")


def test_gross_margin_with_no_data_returns_none_percentages_not_zero():
    result = compute_gross_margin([])

    assert result.revenue_with_known_cost == Decimal("0.00")
    assert result.gross_margin_pct is None
    assert result.cost_data_coverage_pct is None


def test_revenue_change_percentage():
    trend = compute_revenue_change(Decimal("1100"), Decimal("1000"))
    assert trend.change_pct == Decimal("10.0")

    decline = compute_revenue_change(Decimal("900"), Decimal("1000"))
    assert decline.change_pct == Decimal("-10.0")


def test_revenue_change_with_zero_previous_period_has_no_meaningful_percentage():
    trend = compute_revenue_change(Decimal("500"), Decimal("0"))
    assert trend.current == Decimal("500.00")
    assert trend.change_pct is None


def test_rank_products_by_margin_excludes_products_with_unknown_cost():
    aggregates = [
        _aggregate(_P1, units_sold=10, revenue="1000", revenue_with_known_cost="1000", cogs="800"),  # 20% margin
        _aggregate(_P2, units_sold=5, revenue="500", revenue_with_known_cost="500", cogs="100"),  # 80% margin
        _aggregate(_P3, units_sold=3, revenue="300", revenue_with_known_cost="0", cogs="0"),  # no cost data
    ]
    products_by_id = {_P1: "Chain", _P2: "Saddle", _P3: "Mystery Item"}

    top, bottom, excluded_count = rank_products_by_margin(aggregates, products_by_id, top_n=5)

    assert excluded_count == 1
    assert {row.product_id for row in top} == {_P1, _P2}
    assert {row.product_id for row in bottom} == set()  # fewer than top_n * 2 candidates
    assert top[0].product_id == _P2  # higher gross profit first ($400 vs $200)


def test_rank_products_by_margin_top_and_bottom_dont_overlap_with_enough_products():
    aggregates = [
        _aggregate(uuid.uuid4(), units_sold=1, revenue=str(100 * i), revenue_with_known_cost=str(100 * i), cogs="10")
        for i in range(1, 8)
    ]
    products_by_id = {a.product_id: f"Product {i}" for i, a in enumerate(aggregates)}

    top, bottom, excluded_count = rank_products_by_margin(aggregates, products_by_id, top_n=3)

    assert excluded_count == 0
    assert len(top) == 3
    assert len(bottom) == 3
    assert {row.product_id for row in top}.isdisjoint({row.product_id for row in bottom})
    # Bottom is ascending (worst first)
    assert bottom[0].gross_profit <= bottom[1].gross_profit <= bottom[2].gross_profit
