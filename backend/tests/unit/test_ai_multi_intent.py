"""Unit coverage for app/ai/service.py's multi-intent classify parsing —
the "intents" array shape _parse_intent_json validates (splitting,
capping at _MAX_SUBINTENTS, and the defensive fallback for a model that
ignores the array-wrapping instruction). The full multi-part
answer_question pipeline (merged context, part markers, per-part
guardrail) is covered in tests/integration/test_ai_chat.py instead — this
file is purely about turning the classify call's raw JSON into a
list[ClassifyResult].
"""

import json
import logging
from datetime import date

import pytest

from app.ai.service import _MAX_SUBINTENTS, ClassifyResult, _parse_intent_json

_TODAY = date(2026, 6, 24)


@pytest.fixture
def _reenable_service_logger(monkeypatch):
    # See test_ai_explicit_date_parsing.py's own fixture of the same name
    # for why this is necessary (Alembic's fileConfig disables loggers).
    monkeypatch.setattr(logging.getLogger("app.ai.service"), "disabled", False)


def test_intents_array_with_one_object_returns_a_single_element_list():
    content = json.dumps({"intents": [{"intent": "financial_performance", "period": None, "metric": None}]})
    result = _parse_intent_json(content, today=_TODAY)
    assert len(result) == 1
    assert result[0].intent == "financial_performance"


def test_intents_array_with_two_objects_returns_both_in_order():
    content = json.dumps(
        {
            "intents": [
                {"intent": "financial_performance", "period": None, "metric": None},
                {"intent": "forecast", "period": None, "metric": None, "horizon_days": 14},
            ]
        }
    )
    result = _parse_intent_json(content, today=_TODAY)
    assert [r.intent for r in result] == ["financial_performance", "forecast"]
    assert result[1].horizon_days == 14


def test_weather_sales_analysis_fields_are_parsed_and_bounded():
    content = json.dumps(
        {
            "intents": [
                {
                    "intent": "weather_sales_analysis",
                    "weather_bucket": "rainy",
                    "entity_type": "product",
                    "rank_direction": "both",
                    "limit": 7,
                }
            ]
        }
    )

    result = _parse_intent_json(content, today=_TODAY)

    assert result == [
        ClassifyResult(
            intent="weather_sales_analysis",
            weather_bucket="rainy",
            entity_type="product",
            rank_direction="both",
            limit=7,
        )
    ]


def test_invalid_weather_sales_analysis_fields_fail_closed():
    content = json.dumps(
        {
            "intents": [
                {
                    "intent": "weather_sales_analysis",
                    "weather_bucket": "hail",
                    "entity_type": "sku",
                    "rank_direction": "middle",
                    "limit": 100,
                }
            ]
        }
    )

    result = _parse_intent_json(content, today=_TODAY)

    assert result == [ClassifyResult(intent="weather_sales_analysis")]


def test_intents_array_caps_at_max_subintents():
    # A hypothetical model ignoring the "cap at 3" instruction and
    # listing 5 — server-side enforcement, never trust the model's count.
    content = json.dumps({"intents": [{"intent": "financial_performance", "period": None} for _ in range(5)]})
    result = _parse_intent_json(content, today=_TODAY)
    assert len(result) == _MAX_SUBINTENTS == 3


def test_bare_object_without_intents_key_falls_back_to_a_single_element_list():
    # Defensive backward-compat: a free-tier model has a documented
    # history of not always following the exact JSON shape asked for —
    # this is also exactly the shape every pre-multi-intent test in
    # test_ai_chat.py already sends via _classify_response.
    content = json.dumps({"intent": "retail_operations", "period": "last_completed_week", "metric": None})
    result = _parse_intent_json(content, today=_TODAY)
    assert len(result) == 1
    assert result[0].intent == "retail_operations"
    assert result[0].period == "last_completed_week"


def test_intents_list_with_non_dict_items_skips_them():
    content = json.dumps({"intents": ["not an object", {"intent": "forecast", "period": None}, 42]})
    result = _parse_intent_json(content, today=_TODAY)
    assert len(result) == 1
    assert result[0].intent == "forecast"


def test_empty_intents_list_falls_back_to_out_of_scope(caplog, _reenable_service_logger):
    content = json.dumps({"intents": []})
    with caplog.at_level("WARNING"):
        result = _parse_intent_json(content, today=_TODAY)
    assert result == [ClassifyResult(intent="out_of_scope")]
    assert any('"intents"' in record.message for record in caplog.records)


def test_intents_list_with_only_non_dict_items_falls_back_to_out_of_scope(caplog, _reenable_service_logger):
    content = json.dumps({"intents": ["nope", 1, None]})
    with caplog.at_level("WARNING"):
        result = _parse_intent_json(content, today=_TODAY)
    assert result == [ClassifyResult(intent="out_of_scope")]
    assert any("no usable objects" in record.message for record in caplog.records)


def test_missing_intents_and_intent_keys_falls_back_to_out_of_scope(caplog, _reenable_service_logger):
    content = json.dumps({"period": "default_recent"})
    with caplog.at_level("WARNING"):
        result = _parse_intent_json(content, today=_TODAY)
    assert result == [ClassifyResult(intent="out_of_scope")]
