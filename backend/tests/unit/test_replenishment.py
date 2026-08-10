from decimal import Decimal

from app.analytics.findings import DEFAULT_LOW_STOCK_THRESHOLD_DAYS
from app.analytics.replenishment import DEFAULT_SAFETY_BUFFER_DAYS, recommend_low_stock_threshold


def test_recommendation_falls_back_to_default_when_lead_time_unknown():
    result = recommend_low_stock_threshold(lead_time_days=None, current_threshold_days=Decimal("7"))

    assert result.basis == "default_fallback"
    assert result.recommended_threshold_days == DEFAULT_LOW_STOCK_THRESHOLD_DAYS
    assert result.lead_time_days is None
    assert result.current_threshold_days == Decimal("7")


def test_recommendation_uses_supplier_lead_time_plus_safety_buffer_when_known():
    result = recommend_low_stock_threshold(lead_time_days=Decimal("10"), current_threshold_days=None)

    assert result.basis == "supplier_lead_time"
    assert result.recommended_threshold_days == Decimal("13.0")  # 10 + 3
    assert result.lead_time_days == Decimal("10")
    assert result.safety_buffer_days == DEFAULT_SAFETY_BUFFER_DAYS


def test_recommendation_accepts_a_custom_safety_buffer():
    result = recommend_low_stock_threshold(
        lead_time_days=Decimal("5"), current_threshold_days=None, safety_buffer_days=Decimal("1")
    )

    assert result.recommended_threshold_days == Decimal("6.0")
    assert result.safety_buffer_days == Decimal("1")


def test_recommendation_is_deterministic_for_the_same_inputs():
    # Same inputs must always produce the same output — no hidden state,
    # no randomness, no AI in this formula at all (CLAUDE.md's Core Rule).
    a = recommend_low_stock_threshold(lead_time_days=Decimal("7.5"), current_threshold_days=Decimal("7"))
    b = recommend_low_stock_threshold(lead_time_days=Decimal("7.5"), current_threshold_days=Decimal("7"))
    assert a == b
