import uuid
from decimal import Decimal

from app.analytics.financial import GrossMarginResult, ProductMarginRow, ReturnsSummary, RevenueTrend
from app.analytics.findings import (
    DEFAULT_LOW_STOCK_THRESHOLD_DAYS,
    Finding,
    build_recommendations,
    evaluate_dead_stock,
    evaluate_high_return_rate,
    evaluate_incomplete_cost_data,
    evaluate_low_gross_margin,
    evaluate_low_stock,
    evaluate_products_at_loss,
    evaluate_revenue_decline,
    resolve_low_stock_threshold,
)
from app.analytics.retail import DeadStockEntry, StockCoverRow

_P1, _P2 = uuid.uuid4(), uuid.uuid4()


def _gross_margin(*, total_revenue, revenue_with_known_cost, cogs, gross_profit, gross_margin_pct, coverage_pct):
    return GrossMarginResult(
        total_revenue=Decimal(total_revenue),
        revenue_with_known_cost=Decimal(revenue_with_known_cost),
        cogs=Decimal(cogs),
        gross_profit=Decimal(gross_profit),
        gross_margin_pct=Decimal(gross_margin_pct) if gross_margin_pct is not None else None,
        cost_data_coverage_pct=Decimal(coverage_pct) if coverage_pct is not None else None,
    )


def _stock_cover_row(product_id=_P1, *, name="Widget", stock_on_hand=10, units_sold=0, cover_days, revenue="0"):
    return StockCoverRow(
        product_id=product_id,
        name=name,
        stock_on_hand=stock_on_hand,
        units_sold_in_period=units_sold,
        cover_days=Decimal(cover_days) if cover_days is not None else None,
        revenue_in_period=Decimal(revenue),
    )


# --- revenue_decline ---------------------------------------------------


def test_revenue_decline_triggers_past_the_threshold():
    trend = RevenueTrend(current=Decimal("900"), previous=Decimal("1000"), change_pct=Decimal("-10.0"))
    findings = evaluate_revenue_decline(trend)
    assert len(findings) == 1
    assert findings[0].type == "revenue_decline"
    assert findings[0].severity == "warning"


def test_revenue_decline_does_not_trigger_on_growth_or_small_dip():
    growth = RevenueTrend(current=Decimal("1100"), previous=Decimal("1000"), change_pct=Decimal("10.0"))
    small_dip = RevenueTrend(current=Decimal("950"), previous=Decimal("1000"), change_pct=Decimal("-5.0"))
    assert evaluate_revenue_decline(growth) == []
    assert evaluate_revenue_decline(small_dip) == []


def test_revenue_decline_does_not_trigger_with_no_previous_period_data():
    no_baseline = RevenueTrend(current=Decimal("500"), previous=Decimal("0"), change_pct=None)
    assert evaluate_revenue_decline(no_baseline) == []


# --- high_return_rate ----------------------------------------------------


def _returns_summary(*, gross="1000", returns="0", count=0, rate="0.0"):
    return ReturnsSummary(
        gross_revenue=Decimal(gross),
        returns_amount=Decimal(returns),
        return_count=count,
        net_revenue=Decimal(gross) - Decimal(returns),
        return_rate_pct=Decimal(rate) if rate is not None else None,
    )


def test_high_return_rate_triggers_past_the_threshold():
    summary = _returns_summary(gross="1000", returns="150", count=3, rate="15.0")
    findings = evaluate_high_return_rate(summary)
    assert len(findings) == 1
    assert findings[0].type == "high_return_rate"
    assert findings[0].severity == "warning"
    assert findings[0].evidence["return_count"] == 3


def test_high_return_rate_does_not_trigger_below_threshold():
    summary = _returns_summary(gross="1000", returns="50", count=1, rate="5.0")
    assert evaluate_high_return_rate(summary) == []


def test_high_return_rate_does_not_trigger_with_no_gross_revenue():
    summary = _returns_summary(gross="0", returns="0", count=0, rate=None)
    assert evaluate_high_return_rate(summary) == []


# --- low_gross_margin / incomplete_cost_data ----------------------------


def test_low_gross_margin_triggers_below_threshold():
    margin = _gross_margin(
        total_revenue="1000", revenue_with_known_cost="1000", cogs="900", gross_profit="100",
        gross_margin_pct="10.0", coverage_pct="100.0",
    )
    findings = evaluate_low_gross_margin(margin)
    assert len(findings) == 1 and findings[0].type == "low_gross_margin"


def test_low_gross_margin_does_not_trigger_at_or_above_threshold():
    margin = _gross_margin(
        total_revenue="1000", revenue_with_known_cost="1000", cogs="800", gross_profit="200",
        gross_margin_pct="20.0", coverage_pct="100.0",
    )
    assert evaluate_low_gross_margin(margin) == []


def test_low_gross_margin_does_not_trigger_with_no_known_cost_data():
    margin = _gross_margin(
        total_revenue="1000", revenue_with_known_cost="0", cogs="0", gross_profit="0",
        gross_margin_pct=None, coverage_pct="0.0",
    )
    assert evaluate_low_gross_margin(margin) == []


def test_incomplete_cost_data_triggers_below_threshold():
    margin = _gross_margin(
        total_revenue="1000", revenue_with_known_cost="300", cogs="200", gross_profit="100",
        gross_margin_pct="33.3", coverage_pct="30.0",
    )
    findings = evaluate_incomplete_cost_data(margin)
    assert len(findings) == 1
    assert findings[0].evidence["total_revenue"] == Decimal("1000")


def test_incomplete_cost_data_does_not_trigger_with_good_coverage():
    margin = _gross_margin(
        total_revenue="1000", revenue_with_known_cost="900", cogs="700", gross_profit="200",
        gross_margin_pct="22.2", coverage_pct="90.0",
    )
    assert evaluate_incomplete_cost_data(margin) == []


# --- product_selling_at_loss --------------------------------------------


def test_products_at_loss_flags_only_negative_gross_profit_rows():
    rows = [
        ProductMarginRow(product_id=_P1, name="Loser", revenue=Decimal("100"), gross_profit=Decimal("-20"), gross_margin_pct=Decimal("-20.0")),
        ProductMarginRow(product_id=_P2, name="Winner", revenue=Decimal("100"), gross_profit=Decimal("30"), gross_margin_pct=Decimal("30.0")),
    ]
    findings = evaluate_products_at_loss(rows)
    assert len(findings) == 1
    assert findings[0].evidence["product_id"] == str(_P1)


# --- low_stock (the rule Stage C12 will reuse directly) ------------------


def test_low_stock_triggers_within_threshold_as_warning():
    rows = [_stock_cover_row(cover_days="5")]
    findings = evaluate_low_stock(rows, threshold_days=Decimal("7"))
    assert len(findings) == 1
    assert findings[0].severity == "warning"


def test_low_stock_out_of_stock_is_critical():
    rows = [_stock_cover_row(cover_days="0")]
    findings = evaluate_low_stock(rows, threshold_days=Decimal("7"))
    assert findings[0].severity == "critical"


def test_low_stock_does_not_trigger_above_threshold_or_when_unknown():
    plenty = _stock_cover_row(cover_days="30")
    unknown = _stock_cover_row(cover_days=None)
    assert evaluate_low_stock([plenty], threshold_days=Decimal("7")) == []
    assert evaluate_low_stock([unknown], threshold_days=Decimal("7")) == []


def test_low_stock_is_independently_callable_with_just_rows_and_a_threshold():
    # The property Stage C12 depends on: no FinancialPerformanceSummary/
    # RetailOperationsSummary object required, just the rows.
    rows = [_stock_cover_row(product_id=_P1, name="Chain Lube", cover_days="2", revenue="50.00")]
    findings = evaluate_low_stock(rows, threshold_days=Decimal("3"))
    assert findings[0].evidence["revenue_in_period"] == Decimal("50.00")


# --- dead_stock -----------------------------------------------------------


def test_dead_stock_produces_one_finding_per_entry():
    entries = [
        DeadStockEntry(product_id=_P1, name="Old Stock", stock_on_hand=20, value_at_cost=Decimal("100.00")),
    ]
    findings = evaluate_dead_stock(entries)
    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert findings[0].evidence["value_at_cost"] == Decimal("100.00")


# --- build_recommendations ranking ----------------------------------------


def test_build_recommendations_ranks_by_severity_then_impact():
    findings = [
        Finding(
            type="dead_stock", severity="info", message="m", rule_id="dead_stock",
            evidence={"product_id": "x", "name": "n", "stock_on_hand": 5, "value_at_cost": Decimal("50")},
        ),
        Finding(
            type="low_stock", severity="critical", message="m", rule_id="low_stock",
            evidence={"product_id": "y", "name": "n", "stock_on_hand": 0, "cover_days": Decimal("0"),
                      "revenue_in_period": Decimal("10"), "threshold_days": Decimal("7")},
        ),
        Finding(
            type="revenue_decline", severity="warning", message="m", rule_id="revenue_decline",
            evidence={"current": Decimal("500"), "previous": Decimal("1000"), "change_pct": Decimal("-50.0")},
        ),
    ]
    recommendations = build_recommendations(findings)
    # critical first, then warning, then info — regardless of impact_score
    assert [r.severity for r in recommendations] == ["critical", "warning", "info"]


def test_build_recommendations_ranks_same_severity_by_impact_score_descending():
    findings = [
        Finding(
            type="low_stock", severity="warning", message="m", rule_id="low_stock",
            evidence={"product_id": "a", "name": "Low value", "stock_on_hand": 1, "cover_days": Decimal("5"),
                      "revenue_in_period": Decimal("10"), "threshold_days": Decimal("7")},
        ),
        Finding(
            type="low_stock", severity="warning", message="m", rule_id="low_stock",
            evidence={"product_id": "b", "name": "High value", "stock_on_hand": 1, "cover_days": Decimal("5"),
                      "revenue_in_period": Decimal("500"), "threshold_days": Decimal("7")},
        ),
    ]
    recommendations = build_recommendations(findings)
    assert recommendations[0].evidence["name"] == "High value"
    assert recommendations[1].evidence["name"] == "Low value"


def test_build_recommendations_traces_every_recommendation_back_to_its_finding_type():
    findings = evaluate_revenue_decline(RevenueTrend(current=Decimal("0"), previous=Decimal("100"), change_pct=Decimal("-100.0")))
    recommendations = build_recommendations(findings)
    assert recommendations[0].finding_type == "revenue_decline"
    assert recommendations[0].title  # comes from the approved library, non-empty


# --- resolve_low_stock_threshold (Stage C12, PR-9.3) -----------------------


def test_resolve_low_stock_threshold_product_override_wins():
    assert resolve_low_stock_threshold(Decimal("3"), Decimal("14")) == Decimal("3")


def test_resolve_low_stock_threshold_falls_back_to_category():
    assert resolve_low_stock_threshold(None, Decimal("14")) == Decimal("14")


def test_resolve_low_stock_threshold_falls_back_to_default_when_both_unset():
    assert resolve_low_stock_threshold(None, None) == DEFAULT_LOW_STOCK_THRESHOLD_DAYS
