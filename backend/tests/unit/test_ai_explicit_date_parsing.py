"""Covers app/ai/service.py's server-side validation of the classify
call's start_date/end_date/search_term fields — these come straight from
the model's JSON output and must never be trusted past a parse+bounds
check, exactly the same "fail closed, never guess" posture as every
other field _parse_intent_json already validated before this pass.

Every `_parse_intent_json` call here passes a bare (non-array-wrapped)
`{"intent": ...}` object — the deliberate backward-compat fallback path
(see _parse_intent_json's own docstring) that treats it as a
single-element "intents" list, so `result[0]` below is always that one
sub-intent. The multi-intent "intents" array shape itself (splitting,
capping at _MAX_SUBINTENTS, malformed-item handling) is covered in
test_ai_multi_intent.py instead.
"""

import logging
from datetime import date

import pytest

from app.ai.service import ClassifyResult, _parse_explicit_dates, _parse_intent_json

_TODAY = date(2026, 6, 24)


@pytest.fixture
def _reenable_service_logger(monkeypatch):
    """Alembic's own CLI calls logging.config.fileConfig(...), which
    defaults to disable_existing_loggers=True — a real, live-encountered
    gotcha: any integration test that runs a migration (this codebase's
    conftest does, per-test) silently disables app.ai.service's logger
    for the rest of the pytest session, so a caplog assertion here would
    pass or fail for the wrong reason depending on run order/what ran
    first, rather than on whether _parse_intent_json actually logs.
    Forces it back on for the duration of one test; monkeypatch restores
    the previous value afterward, same as every other fixture here."""
    monkeypatch.setattr(logging.getLogger("app.ai.service"), "disabled", False)


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
    assert len(result) == 1
    assert isinstance(result[0], ClassifyResult)
    assert result[0].intent == "financial_performance"
    assert result[0].period == "explicit_date"
    assert result[0].start_date == date(2026, 6, 24)
    assert result[0].end_date == date(2026, 6, 24)


def test_parse_intent_json_falls_back_to_default_recent_when_explicit_date_is_unparseable():
    content = '{"intent": "financial_performance", "period": "explicit_date", "start_date": "bogus", "metric": null}'
    result = _parse_intent_json(content, today=_TODAY)[0]
    assert result.period == "default_recent"
    assert result.start_date is None
    assert result.end_date is None


def test_parse_intent_json_extracts_search_term():
    content = '{"intent": "product_lookup", "period": null, "search_term": "Chain Lube"}'
    result = _parse_intent_json(content, today=_TODAY)[0]
    assert result.intent == "product_lookup"
    assert result.search_term == "Chain Lube"


def test_parse_intent_json_treats_blank_search_term_as_none():
    content = '{"intent": "product_lookup", "period": null, "search_term": "   "}'
    result = _parse_intent_json(content, today=_TODAY)[0]
    assert result.search_term is None


def test_parse_intent_json_caps_an_overlong_search_term():
    overlong = "x" * 500
    content = f'{{"intent": "product_lookup", "period": null, "search_term": "{overlong}"}}'
    result = _parse_intent_json(content, today=_TODAY)[0]
    assert len(result.search_term) == 200


def test_parse_intent_json_rejects_unknown_intent():
    content = '{"intent": "delete_everything", "period": null}'
    result = _parse_intent_json(content, today=_TODAY)[0]
    assert result.intent == "out_of_scope"


# --- logging the malformed-output cases -------------------------------
# Real regression found live: a newly added fallback model returning
# unparseable content silently defaulted to out_of_scope with zero trace
# in the logs — identical, from the outside, to the model genuinely
# deciding a question wasn't about this business. Each of these cases is
# now logged so the two are distinguishable during live debugging.


def test_parse_intent_json_logs_a_warning_when_content_is_none(caplog, _reenable_service_logger):
    with caplog.at_level("WARNING"):
        result = _parse_intent_json(None, today=_TODAY)
    assert result[0].intent == "out_of_scope"
    assert any("no content" in record.message for record in caplog.records)


def test_parse_intent_json_logs_a_warning_on_non_json_content(caplog, _reenable_service_logger):
    with caplog.at_level("WARNING"):
        result = _parse_intent_json("this is not json", today=_TODAY)
    assert result[0].intent == "out_of_scope"
    assert any("non-JSON" in record.message for record in caplog.records)


def test_parse_intent_json_logs_a_warning_on_a_json_array_instead_of_an_object(caplog, _reenable_service_logger):
    with caplog.at_level("WARNING"):
        result = _parse_intent_json("[1, 2, 3]", today=_TODAY)
    assert result[0].intent == "out_of_scope"
    assert any("wasn't an object" in record.message for record in caplog.records)


def test_parse_intent_json_logs_a_warning_on_an_unrecognised_intent(caplog, _reenable_service_logger):
    with caplog.at_level("WARNING"):
        result = _parse_intent_json('{"intent": "delete_everything", "period": null}', today=_TODAY)
    assert result[0].intent == "out_of_scope"
    assert any("unrecognised intent" in record.message for record in caplog.records)


def test_parse_intent_json_does_not_log_when_the_model_genuinely_says_out_of_scope(caplog, _reenable_service_logger):
    # A real, valid "not about this business" verdict must stay silent —
    # logging every legitimate refusal would drown out the cases above.
    with caplog.at_level("WARNING"):
        result = _parse_intent_json('{"intent": "out_of_scope", "period": null}', today=_TODAY)
    assert result[0].intent == "out_of_scope"
    assert caplog.records == []
