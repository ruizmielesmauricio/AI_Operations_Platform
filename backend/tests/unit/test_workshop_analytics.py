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
    labour_cost_known_revenue_with_known_tax="0",
    tax_amount_known="0",
    labour_cost_for_known_tax="0",
):
    return RepairPeriodTotals(
        repair_count=repair_count,
        repairs_with_known_price=repairs_with_known_price,
        revenue=Decimal(revenue),
        repairs_with_known_price_and_labour=repairs_with_known_price_and_labour,
        labour_cost_known_revenue=Decimal(labour_cost_known_revenue),
        labour_cost=Decimal(labour_cost),
        labour_cost_known_revenue_with_known_tax=Decimal(labour_cost_known_revenue_with_known_tax),
        tax_amount_known=Decimal(tax_amount_known),
        labour_cost_for_known_tax=Decimal(labour_cost_for_known_tax),
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


# --- Tax-inclusive margin (mirrors app/analytics/financial.py's
# net_gross_margin_pct fix, v1.13 — same bug shape reported live for
# repairs: price_charged on a workshop invoice is very often a
# tax-inclusive total, so gross_margin_pct alone can overstate true
# margin wherever tax isn't known). --------------------------------------


def test_workshop_margin_with_no_tax_data_leaves_net_fields_none():
    totals = _totals(
        repair_count=1,
        repairs_with_known_price=1,
        revenue="130.00",
        repairs_with_known_price_and_labour=1,
        labour_cost_known_revenue="130.00",
        labour_cost="30.00",
    )
    result = compute_workshop_margin(totals)

    assert result.gross_margin_pct == Decimal("76.9")  # unaffected, no tax data
    assert result.net_gross_profit is None
    assert result.net_gross_margin_pct is None
    assert result.tax_data_coverage_pct == Decimal("0.0")


def test_workshop_margin_computes_net_of_tax_when_fully_known():
    # One repair: price_charged 130.00 (tax-inclusive, 10.00 of which is
    # tax), labour cost 30.00. Net revenue is 120.00, so net margin is
    # (120 - 30) / 120 = 75.0%, distinctly lower than gross_margin_pct's
    # 76.9% (100/130) — the exact overstatement this fix closes.
    totals = _totals(
        repair_count=1,
        repairs_with_known_price=1,
        revenue="130.00",
        repairs_with_known_price_and_labour=1,
        labour_cost_known_revenue="130.00",
        labour_cost="30.00",
        labour_cost_known_revenue_with_known_tax="130.00",
        tax_amount_known="10.00",
        labour_cost_for_known_tax="30.00",
    )
    result = compute_workshop_margin(totals)

    assert result.gross_margin_pct == Decimal("76.9")  # unchanged — still shown as a fallback
    assert result.net_gross_profit == Decimal("90.00")  # (130-10) - 30
    assert result.net_gross_margin_pct == Decimal("75.0")  # 90 / 120
    assert result.tax_data_coverage_pct == Decimal("100.0")


def test_workshop_margin_net_of_tax_excludes_tax_unknown_repairs_not_blend_them():
    # Two repairs, both with known price and labour cost, but only one
    # has a known tax_amount. The tax-unknown repair (whose price may
    # still include tax) must never be folded into the "confirmed net"
    # figure — net_gross_profit/net_gross_margin_pct should reflect only
    # the tax-known repair, same as the sales-side equivalent test.
    totals = _totals(
        repair_count=2,
        repairs_with_known_price=2,
        revenue="230.00",  # 130 (tax-known) + 100 (tax-unknown)
        repairs_with_known_price_and_labour=2,
        labour_cost_known_revenue="230.00",
        labour_cost="55.00",  # 30 (tax-known) + 25 (tax-unknown)
        labour_cost_known_revenue_with_known_tax="130.00",
        tax_amount_known="10.00",
        labour_cost_for_known_tax="30.00",
    )
    result = compute_workshop_margin(totals)

    assert result.gross_margin_pct == Decimal("76.1")  # (230-55)/230 — both repairs
    assert result.net_gross_profit == Decimal("90.00")  # only the tax-known repair
    assert result.net_gross_margin_pct == Decimal("75.0")  # 90 / 120
    assert result.tax_data_coverage_pct == Decimal("56.5")  # 130 / 230
