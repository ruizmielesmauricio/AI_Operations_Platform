from decimal import Decimal

from app.analytics.types import RepairPeriodTotals
from app.analytics.workshop import compute_workshop_margin


def _totals(
    *,
    repair_count,
    repairs_with_known_price,
    revenue,
    repairs_with_known_price_and_labour,
    labour_cost_known_revenue,
    labour_cost,
):
    return RepairPeriodTotals(
        repair_count=repair_count,
        repairs_with_known_price=repairs_with_known_price,
        revenue=Decimal(revenue),
        repairs_with_known_price_and_labour=repairs_with_known_price_and_labour,
        labour_cost_known_revenue=Decimal(labour_cost_known_revenue),
        labour_cost=Decimal(labour_cost),
    )


def test_full_data_computes_revenue_margin_and_average_ticket():
    totals = _totals(
        repair_count=2,
        repairs_with_known_price=2,
        revenue="130.00",
        repairs_with_known_price_and_labour=2,
        labour_cost_known_revenue="130.00",
        labour_cost="30.00",
    )
    result = compute_workshop_margin(totals)

    assert result.repair_count == 2
    assert result.revenue == Decimal("130.00")
    assert result.revenue_coverage_pct == Decimal("100.0")
    assert result.gross_profit == Decimal("100.00")
    assert result.gross_margin_pct == Decimal("76.9")  # 100/130
    assert result.labour_cost_coverage_pct == Decimal("100.0")
    assert result.average_ticket == Decimal("65.00")  # 130/2


def test_repair_with_price_but_no_labour_cost_counts_toward_revenue_not_margin():
    # One repair has both known (80/30), one has price only (50).
    totals = _totals(
        repair_count=2,
        repairs_with_known_price=2,
        revenue="130.00",
        repairs_with_known_price_and_labour=1,
        labour_cost_known_revenue="80.00",
        labour_cost="30.00",
    )
    result = compute_workshop_margin(totals)

    assert result.revenue == Decimal("130.00")  # both prices counted
    assert result.revenue_coverage_pct == Decimal("100.0")
    assert result.gross_profit == Decimal("50.00")  # only the fully-known repair
    assert result.gross_margin_pct == Decimal("62.5")  # 50/80
    assert result.labour_cost_coverage_pct == Decimal("61.5")  # 80/130
    assert result.average_ticket == Decimal("65.00")  # revenue still divides by known-price count


def test_repair_with_no_price_charged_lowers_revenue_coverage():
    # description-only repair: no price, no labour.
    totals = _totals(
        repair_count=2,
        repairs_with_known_price=1,
        revenue="80.00",
        repairs_with_known_price_and_labour=1,
        labour_cost_known_revenue="80.00",
        labour_cost="30.00",
    )
    result = compute_workshop_margin(totals)

    assert result.revenue_coverage_pct == Decimal("50.0")  # 1 of 2 repairs priced
    assert result.average_ticket == Decimal("80.00")  # 80 / 1


def test_zero_repairs_returns_none_percentages_and_ticket_not_zero():
    totals = _totals(
        repair_count=0,
        repairs_with_known_price=0,
        revenue="0",
        repairs_with_known_price_and_labour=0,
        labour_cost_known_revenue="0",
        labour_cost="0",
    )
    result = compute_workshop_margin(totals)

    assert result.repair_count == 0
    assert result.revenue == Decimal("0.00")
    assert result.revenue_coverage_pct is None
    assert result.gross_margin_pct is None
    assert result.labour_cost_coverage_pct is None
    assert result.average_ticket is None
