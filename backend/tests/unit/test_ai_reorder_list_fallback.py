"""ORLA-91 eval findings around the reorder priority list."""

from app.ai.service import _REORDER_LIST_ONLY_INTRO, _Part, _reorder_list_only_answer, _trim_forecast

PRODUCTS = [
    {"name": "Trailblazer MTB 29", "suggested_reorder_quantity": 4, "days_of_cover_at_forecast_rate": "0"},
    {"name": "Inner Tube 29x2.2", "suggested_reorder_quantity": 34, "days_of_cover_at_forecast_rate": "2"},
]


def test_rejected_reorder_answer_falls_back_to_the_deterministic_list():
    part = _Part(intent="forecast", context={}, all_products_for_priority_list=PRODUCTS)
    answer = _reorder_list_only_answer(part, "If I had €2,000 to spend on restocking, what should I prioritise?", None)
    assert answer.startswith(_REORDER_LIST_ONLY_INTRO)
    assert "1. Trailblazer MTB 29 — 4 units" in answer
    assert "2. Inner Tube 29x2.2 — 34 units" in answer


def test_no_list_fallback_for_a_plain_revenue_forecast_question():
    part = _Part(intent="forecast", context={}, all_products_for_priority_list=PRODUCTS)
    assert _reorder_list_only_answer(part, "What's my revenue forecast for next week?", None) is None
    other = _Part(intent="financial_performance", context={})
    assert _reorder_list_only_answer(other, "What should I reorder?", None) is None


def test_forecast_products_carry_their_urgency_rank_in_order():
    forecast = {"revenue": {"result": {"daily": []}}, "products": [{"name": "A"}, {"name": "B"}]}
    trimmed = _trim_forecast(forecast)
    assert [(p["urgency_rank"], p["name"]) for p in trimmed["products"]] == [(1, "A"), (2, "B")]
