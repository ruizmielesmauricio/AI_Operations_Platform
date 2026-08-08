from decimal import Decimal

from app.analytics.financial import RevenueTrend
from app.analytics.report_narrative import build_executive_narrative


def _trend(current="1000.00", previous="1000.00", change_pct=None):
    return RevenueTrend(current=Decimal(current), previous=Decimal(previous), change_pct=Decimal(change_pct) if change_pct else None)


def test_narrative_reports_a_material_revenue_increase():
    sentences = build_executive_narrative(
        revenue=_trend(change_pct="12.0"), low_stock_count=0, dead_stock_count=0, top_recommendation_title=None
    )
    assert "increased by 12.0%" in sentences[0]


def test_narrative_reports_a_material_revenue_decrease():
    sentences = build_executive_narrative(
        revenue=_trend(change_pct="-15.0"), low_stock_count=0, dead_stock_count=0, top_recommendation_title=None
    )
    assert "decreased by 15.0%" in sentences[0]


def test_narrative_reports_stable_revenue_below_the_material_threshold():
    sentences = build_executive_narrative(
        revenue=_trend(change_pct="2.0"), low_stock_count=0, dead_stock_count=0, top_recommendation_title=None
    )
    assert "broadly stable" in sentences[0]


def test_narrative_handles_no_previous_period_to_compare_against():
    sentences = build_executive_narrative(
        revenue=_trend(change_pct=None), low_stock_count=0, dead_stock_count=0, top_recommendation_title=None
    )
    assert "no prior period" in sentences[0]


def test_narrative_flags_low_stock_and_dead_stock_counts():
    sentences = build_executive_narrative(
        revenue=_trend(change_pct="0.0"), low_stock_count=3, dead_stock_count=2, top_recommendation_title=None
    )
    assert any("2 product(s) had stock on hand but no sales" in s for s in sentences)
    assert any("3 product(s) are currently low on stock" in s for s in sentences)


def test_narrative_reports_all_clear_when_nothing_is_flagged():
    sentences = build_executive_narrative(
        revenue=_trend(change_pct="0.0"), low_stock_count=0, dead_stock_count=0, top_recommendation_title=None
    )
    assert any("No low-stock or dead-stock issues" in s for s in sentences)


def test_narrative_includes_the_top_recommendation_when_given():
    sentences = build_executive_narrative(
        revenue=_trend(change_pct="0.0"),
        low_stock_count=0,
        dead_stock_count=0,
        top_recommendation_title="Restock brake pads",
    )
    assert sentences[-1] == "The highest-priority recommendation this period: Restock brake pads."
