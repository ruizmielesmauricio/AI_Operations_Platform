"""ORLA-91 eval finding: the free classify model sometimes returns almost-
valid JSON (a stray word between fields, markdown fences, a trailing comma)
and the question was refused as out_of_scope. _parse_intent_json now
salvages the known keys — every value still validated by the same allow-
lists, so nothing outside the fixed intent set can come through."""

from datetime import date

from app.ai.service import _MAX_SUBINTENTS, _parse_intent_json

_TODAY = date(2026, 11, 13)


def test_stray_word_between_fields_is_salvaged():
    content = (
        '{"intents": [{"intent": "financial_performance", "period": "default_recent", "start_date": null, '
        '"end_date": null, probably "metric": null, "search_term": null, "horizon_days": null}]}'
    )
    [result] = _parse_intent_json(content, today=_TODAY)
    assert result.intent == "financial_performance"
    assert result.period == "default_recent"


def test_markdown_fenced_json_is_salvaged_with_dates_and_horizon():
    content = (
        '```json\n{"intents": [{"intent": "financial_performance", "period": "explicit_date", '
        '"start_date": "2026-10-24", "end_date": "2026-10-24"}, {"intent": "forecast", "horizon_days": 14,}]}\n```'
    )
    first, second = _parse_intent_json(content, today=_TODAY)
    assert (first.intent, first.period, first.start_date) == ("financial_performance", "explicit_date", date(2026, 10, 24))
    assert (second.intent, second.horizon_days) == ("forecast", 14)


def test_salvaged_values_are_still_allow_listed():
    content = '{"intents": [{"intent": "delete_everything", "period": "forever"},]}'
    [result] = _parse_intent_json(content, today=_TODAY)
    assert result.intent == "out_of_scope"
    assert result.period == "default_recent"


def test_salvage_caps_at_max_subintents():
    content = "[" + ",".join('{"intent": "forecast"}' for _ in range(_MAX_SUBINTENTS + 2)) + ",]"
    assert len(_parse_intent_json(content, today=_TODAY)) == _MAX_SUBINTENTS


def test_text_with_no_intent_key_still_falls_back_to_out_of_scope():
    [result] = _parse_intent_json("Sorry, I can't classify that.", today=_TODAY)
    assert result.intent == "out_of_scope"
