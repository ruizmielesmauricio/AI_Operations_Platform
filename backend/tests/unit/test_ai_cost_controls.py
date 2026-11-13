"""ORLA-91 cost controls: per-model AI settings, cache-friendly prompts, and
the input-token cuts — pure functions, no DB."""

from datetime import datetime, timezone

from app.ai import client
from app.ai.service import _calendar_month, _cap_report_lists, _trim_findings, _without_internal_fields


def _with(monkeypatch, **updates):
    settings = client.get_settings().model_copy(update=updates)
    monkeypatch.setattr(client, "get_settings", lambda: settings)


def test_model_override_wins_for_the_primary_model(monkeypatch):
    _with(
        monkeypatch, openrouter_model="anthropic/claude-haiku-5.5", ai_reasoning_effort="",
        ai_explain_max_tokens=2500,
        ai_model_overrides='{"anthropic/claude-haiku-5.5": {"reasoning_effort": "low", "explain_max_tokens": 1500}}',
    )
    assert client.ai_setting("reasoning_effort") == "low"
    assert client.ai_setting("explain_max_tokens") == 1500
    assert client.ai_setting("classify_max_tokens") == client.get_settings().ai_classify_max_tokens


def test_other_primary_models_use_the_globals(monkeypatch):
    # Gemma: "low" would switch its reasoning ON, so it must not inherit it.
    _with(
        monkeypatch, openrouter_model="google/gemma-4-31b-it", ai_reasoning_effort="",
        ai_model_overrides='{"anthropic/claude-haiku-5.5": {"reasoning_effort": "low"}}',
    )
    assert client.ai_setting("reasoning_effort") == ""


def test_malformed_overrides_fall_back_to_globals(monkeypatch):
    _with(monkeypatch, ai_model_overrides="not json", ai_explain_max_tokens=2500)
    assert client.ai_setting("explain_max_tokens") == 2500


def test_system_message_puts_static_first_with_a_cache_breakpoint(monkeypatch):
    _with(monkeypatch, ai_prompt_cache_breakpoints=True)
    message = client.system_message("RULES", "DATA")
    assert message["content"][0] == {"type": "text", "text": "RULES", "cache_control": {"type": "ephemeral"}}
    assert message["content"][1] == {"type": "text", "text": "DATA"}
    assert client.message_text(message) == "RULESDATA"


def test_system_message_is_a_plain_string_without_breakpoints(monkeypatch):
    _with(monkeypatch, ai_prompt_cache_breakpoints=False)
    assert client.system_message("RULES", "DATA") == {"role": "system", "content": "RULESDATA"}


def test_ids_and_rule_bookkeeping_are_removed_from_model_context():
    context = {
        "product_id": "683822ad-c093-44bd-a61c-32c9680651bf",
        "name": "Trailblazer MTB 29",
        "category_id": None,
        "business_id": "78b425b8-091f-41ee-a267-06fc0197244e",
        "rows": [{"purchase_id": "94243c59-e55e-46e3-8db7-11bec4ecd7fd", "quantity_received": 40}],
        "rule_id": "low_stock",
        "rule_version": 1,
        "order_id": "PO-7009",  # not a UUID: a reference the user may ask about, kept
    }
    assert _without_internal_fields(context) == {
        "name": "Trailblazer MTB 29", "rows": [{"quantity_received": 40}], "order_id": "PO-7009",
    }


def test_report_lists_are_capped_at_five_with_the_true_total():
    payload = {"findings": {"recommendations": [{"n": i} for i in range(16)]}, "narrative": ["a", "b", "c", "d", "e", "f"]}
    capped = _cap_report_lists(payload)
    assert len(capped["findings"]["recommendations"]) == 5
    assert capped["findings"]["recommendations_shown_of_total"] == "5 of 16"
    assert capped["narrative"] == payload["narrative"]  # plain text lists are kept whole


def test_findings_keep_their_message_and_recommendations_their_evidence():
    findings = {
        "findings": [{"type": "low_stock", "severity": "critical", "message": "X is out of stock.", "evidence": {"a": 1}}],
        "recommendations": [{"title": "Reorder soon", "evidence": {"name": "X", "cover_days": "0"}}],
    }
    trimmed = _trim_findings(findings)
    assert trimmed["findings"] == [{"type": "low_stock", "severity": "critical", "message": "X is out of stock."}]
    assert trimmed["recommendations"][0]["evidence"] == {"name": "X", "cover_days": "0"}


def test_calendar_month_uses_the_business_timezone():
    # 30 Nov 23:30 UTC is already 1 Dec in Auckland.
    start, next_first = _calendar_month("Pacific/Auckland", datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc))
    assert next_first.isoformat() == "2027-01-01"
    assert start == datetime(2026, 11, 30, 11, 0, tzinfo=timezone.utc)  # 1 Dec 00:00 NZDT
