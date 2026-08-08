"""Covers app/ai/service.py's server-side validation of the classify
call's start_date/end_date/search_term fields — these come straight from
the model's JSON output and must never be trusted past a parse+bounds
check, exactly the same "fail closed, never guess" posture as every
other field _parse_intent_json already validated before this pass.
"""

from datetime import date

from app.ai.service import ClassifyResult, _parse_explicit_dates, _parse_intent_json

_TODAY = date(2026, 6, 24)


def test_valid_single_date_is_accepted():
    start, end = _parse_explicit_dates("2026-06-24", None, today=_TODAY)
    assert start == date(2026, 6, 24)
    assert end == date(2026, 6, 24)


def test_valid_range_is_accepted():
    start, end = _parse_explicit_dates("2026-06-01", "2026-06-24", today=_TODAY)
    assert start == date(2026, 6, 1)
    assert end == date(2026, 6, 24)


def test_missing_end_date_defaults_to_start_date():
    start, end = _parse_explicit_dates("2026-06-24", None, today=_TODAY)
    assert start == end


def test_unparseable_end_date_falls_back_to_start_date_rather_than_rejecting_the_whole_range():
    start, end = _parse_explicit_dates("2026-06-24", "not-a-date", today=_TODAY)
    assert start == date(2026, 6, 24)
    assert end == date(2026, 6, 24)


def test_unparseable_start_date_is_rejected():
    start, end = _parse_explicit_dates("24th of June", None, today=_TODAY)
    assert start is None
    assert end is None


def test_start_after_end_is_rejected():
    start, end = _parse_explicit_dates("2026-06-24", "2026-06-01", today=_TODAY)
    assert start is None
    assert end is None


def test_date_far_in_the_past_is_rejected():
    start, end = _parse_explicit_dates("1990-01-01", None, today=_TODAY)
    assert start is None
    assert end is None


def test_date_far_in_the_future_is_rejected():
    start, end = _parse_explicit_dates("2099-01-01", None, today=_TODAY)
    assert start is None
    assert end is None


def test_non_string_start_date_is_rejected():
    start, end = _parse_explicit_dates(None, None, today=_TODAY)
    assert start is None
    assert end is None


def test_parse_intent_json_with_valid_explicit_date_produces_a_classify_result():
    content = '{"intent": "financial_performance", "period": "explicit_date", "start_date": "2026-06-24", "metric": null}'
    result = _parse_intent_json(content, today=_TODAY)
    assert isinstance(result, ClassifyResult)
    assert result.intent == "financial_performance"
    assert result.period == "explicit_date"
    assert result.start_date == date(2026, 6, 24)
    assert result.end_date == date(2026, 6, 24)


def test_parse_intent_json_falls_back_to_default_recent_when_explicit_date_is_unparseable():
    content = '{"intent": "financial_performance", "period": "explicit_date", "start_date": "bogus", "metric": null}'
    result = _parse_intent_json(content, today=_TODAY)
    assert result.period == "default_recent"
    assert result.start_date is None
    assert result.end_date is None


def test_parse_intent_json_extracts_search_term():
    content = '{"intent": "product_lookup", "period": null, "search_term": "Chain Lube"}'
    result = _parse_intent_json(content, today=_TODAY)
    assert result.intent == "product_lookup"
    assert result.search_term == "Chain Lube"


def test_parse_intent_json_treats_blank_search_term_as_none():
    content = '{"intent": "product_lookup", "period": null, "search_term": "   "}'
    result = _parse_intent_json(content, today=_TODAY)
    assert result.search_term is None


def test_parse_intent_json_caps_an_overlong_search_term():
    overlong = "x" * 500
    content = f'{{"intent": "product_lookup", "period": null, "search_term": "{overlong}"}}'
    result = _parse_intent_json(content, today=_TODAY)
    assert len(result.search_term) == 200


def test_parse_intent_json_rejects_unknown_intent():
    content = '{"intent": "delete_everything", "period": null}'
    result = _parse_intent_json(content, today=_TODAY)
    assert result.intent == "out_of_scope"
