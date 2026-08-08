import uuid
from decimal import Decimal

from app.analytics.financial import (
    compute_gross_margin,
    compute_returns_summary,
    compute_revenue_change,
    rank_products_by_margin,
)
from app.analytics.types import ProductPeriodAggregate

_P1, _P2, _P3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _aggregate(
    product_id,
    *,
    units_sold,
    revenue,
    revenue_with_known_cost,
    cogs,
    revenue_with_known_cost_and_tax="0",
    tax_amount_known="0",
    cogs_for_known_tax="0",
):
    return ProductPeriodAggregate(
        product_id=product_id,
        units_sold=units_sold,
        revenue=Decimal(revenue),
        revenue_with_known_cost=Decimal(revenue_with_known_cost),
        cogs=Decimal(cogs),
        revenue_with_known_cost_and_tax=Decimal(revenue_with_known_cost_and_tax),
        tax_amount_known=Decimal(tax_amount_known),
        cogs_for_known_tax=Decimal(cogs_for_known_tax),
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
    assert result.net_gross_margin_pct is None
    assert result.tax_data_coverage_pct is None


def test_gross_margin_with_no_tax_data_leaves_net_fields_none():
    # cost known, tax never mapped — today's gross_margin_pct is
    # unaffected; the net-of-tax fields have nothing to compute from.
    aggregates = [
        _aggregate(_P1, units_sold=10, revenue="1000.00", revenue_with_known_cost="1000.00", cogs="600.00"),
    ]
    result = compute_gross_margin(aggregates)

    assert result.gross_margin_pct == Decimal("40.0")
    assert result.net_gross_profit is None
    assert result.net_gross_margin_pct is None
    assert result.tax_data_coverage_pct == Decimal("0.0")  # 0 of 1000 known-cost revenue has known tax


def test_gross_margin_computes_net_of_tax_when_fully_known():
    # revenue 1000 includes 100 of tax; net revenue 900, cost 600 -> net
    # profit 300, net margin 33.3%, well below the gross (tax-inclusive)
    # 40.0% — this is exactly the overstatement the net figure corrects.
    aggregates = [
        _aggregate(
            _P1, units_sold=10, revenue="1000.00", revenue_with_known_cost="1000.00", cogs="600.00",
            revenue_with_known_cost_and_tax="1000.00", tax_amount_known="100.00", cogs_for_known_tax="600.00",
        ),
    ]
    result = compute_gross_margin(aggregates)

    assert result.gross_margin_pct == Decimal("40.0")  # unchanged, still the gross figure
    assert result.net_gross_profit == Decimal("300.00")  # (1000-100) - 600
    assert result.net_gross_margin_pct == Decimal("33.3")  # 300 / 900
    assert result.tax_data_coverage_pct == Decimal("100.0")


def test_gross_margin_net_of_tax_excludes_tax_unknown_lines_not_blend_them():
    aggregates = [
        # Cost and tax both known -> counts toward the net figure.
        _aggregate(
            _P1, units_sold=10, revenue="1000.00", revenue_with_known_cost="1000.00", cogs="600.00",
            revenue_with_known_cost_and_tax="1000.00", tax_amount_known="100.00", cogs_for_known_tax="600.00",
        ),
        # Cost known, tax unknown -> counts toward gross_margin_pct/cost
        # coverage, but excluded entirely from the net figure.
        _aggregate(_P2, units_sold=5, revenue="500.00", revenue_with_known_cost="500.00", cogs="200.00"),
    ]
    result = compute_gross_margin(aggregates)

    assert result.revenue_with_known_cost == Decimal("1500.00")
    assert result.gross_margin_pct == Decimal("46.7")  # unaffected — still both products
    assert result.net_gross_profit == Decimal("300.00")  # only P1
    assert result.net_gross_margin_pct == Decimal("33.3")
    assert result.tax_data_coverage_pct == Decimal("66.7")  # 1000 of 1500 known-cost revenue


def test_revenue_change_percentage():
    trend = compute_revenue_change(Decimal("1100"), Decimal("1000"))
    assert trend.change_pct == Decimal("10.0")

    decline = compute_revenue_change(Decimal("900"), Decimal("1000"))
    assert decline.change_pct == Decimal("-10.0")


def test_revenue_change_with_zero_previous_period_has_no_meaningful_percentage():
    trend = compute_revenue_change(Decimal("500"), Decimal("0"))
    assert trend.current == Decimal("500.00")
    assert trend.change_pct is None


def test_returns_summary_computes_gross_from_net_plus_returns():
    # net_revenue (Sale.total_amount summed as-is) already has returns
    # netted in — gross is derived from it, not queried separately.
    summary = compute_returns_summary(net_revenue=Decimal("990.01"), returns_amount=Decimal("9.99"), return_count=1)
    assert summary.net_revenue == Decimal("990.01")
    assert summary.returns_amount == Decimal("9.99")
    assert summary.gross_revenue == Decimal("1000.00")
    assert summary.return_count == 1
    assert summary.return_rate_pct == Decimal("1.0")


def test_returns_summary_with_no_returns_has_zero_rate_not_none():
    summary = compute_returns_summary(net_revenue=Decimal("1000.00"), returns_amount=Decimal("0"), return_count=0)
    assert summary.gross_revenue == Decimal("1000.00")
    assert summary.return_rate_pct == Decimal("0.0")


def test_returns_summary_with_zero_gross_revenue_has_no_meaningful_rate():
    summary = compute_returns_summary(net_revenue=Decimal("0"), returns_amount=Decimal("0"), return_count=0)
    assert summary.return_rate_pct is None


def test_rank_products_by_margin_excludes_products_with_unknown_cost():
    aggregates = [
        _aggregate(_P1, units_sold=10, revenue="1000", revenue_with_known_cost="1000", cogs="800"),  # 20% margin
        _aggregate(_P2, units_sold=5, revenue="500", revenue_with_known_cost="500", cogs="100"),  # 80% margin
        _aggregate(_P3, units_sold=3, revenue="300", revenue_with_known_cost="0", cogs="0"),  # no cost data
    ]
    products_by_id = {_P1: "Chain", _P2: "Saddle", _P3: "Mystery Item"}

    top, bottom, excluded_count, all_rows = rank_products_by_margin(aggregates, products_by_id, top_n=5)

    assert excluded_count == 1
    assert {row.product_id for row in top} == {_P1, _P2}
    assert {row.product_id for row in bottom} == set()  # fewer than top_n * 2 candidates
    assert top[0].product_id == _P2  # higher gross profit first ($400 vs $200)
    assert {row.product_id for row in all_rows} == {_P1, _P2}  # unsliced, but still excludes unknown-cost rows


def test_rank_products_by_margin_top_and_bottom_dont_overlap_with_enough_products():
    aggregates = [
        _aggregate(uuid.uuid4(), units_sold=1, revenue=str(100 * i), revenue_with_known_cost=str(100 * i), cogs="10")
        for i in range(1, 8)
    ]
    products_by_id = {a.product_id: f"Product {i}" for i, a in enumerate(aggregates)}

    top, bottom, excluded_count, all_rows = rank_products_by_margin(aggregates, products_by_id, top_n=3)

    assert excluded_count == 0
    assert len(top) == 3
    assert len(bottom) == 3
    assert {row.product_id for row in top}.isdisjoint({row.product_id for row in bottom})
    # Bottom is ascending (worst first)
    assert bottom[0].gross_profit <= bottom[1].gross_profit <= bottom[2].gross_profit
