"""Covers app/ai/service.py::answer_question's full classify->fetch->
explain->guard pipeline against a real (SQLite) database, with the
network call (app.ai.client.chat_completion) monkeypatched — same
mocking style already used for this codebase's other vendor client
modules (r2_client, billing/client.py) in existing tests.
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from app.ai import client
from app.ai.service import answer_question
from app.models.ai_request import AIRequest
from app.repositories.ai_request import AIRequestRepository
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductRepository
from app.repositories.production_event import ProductionEventRepository
from app.settings.config import get_settings

_NOW = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def _canned_response(content: str, *, model: str = "test-model") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
        "model": model,
    }


def _classify_response(intent: str, **extra) -> dict:
    payload = {"intent": intent, "period": None, "metric": None}
    payload.update(extra)
    return _canned_response(json.dumps(payload))


def test_metric_definition_question_never_calls_the_ai_provider(db_session, business_id, monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("chat_completion should not be called for a definition question")

    monkeypatch.setattr(client, "chat_completion", _fail)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What does gross margin mean?", now=_NOW
    )

    assert result.intent == "metric_definition"
    assert result.grounded is True
    assert "cost of goods sold" in result.answer
    assert db_session.query(AIRequest).count() == 0


def test_full_pipeline_classifies_fetches_and_explains(db_session, business_id, monkeypatch):
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            # The classify call.
            return _canned_response(json.dumps({"intent": "financial_performance", "period": "default_recent", "metric": None}))
        # The explain call — echoes a number that's guaranteed present in
        # every FinancialPerformanceOut payload regardless of seeded data.
        return _canned_response("Your gross margin coverage is 0% right now — no cost data has been recorded yet.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW
    )

    assert result.intent == "financial_performance"
    assert len(calls) == 2  # classify, then explain
    assert db_session.query(AIRequest).count() == 2
    assert all(row.lane == "business_qa" for row in db_session.query(AIRequest).all())


def test_out_of_scope_intent_skips_the_explain_call(db_session, business_id, monkeypatch):
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        return _canned_response(json.dumps({"intent": "out_of_scope", "period": None, "metric": None}))

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What's the weather like?", now=_NOW
    )

    assert result.intent == "out_of_scope"
    assert result.grounded is True
    assert len(calls) == 1  # classify only — never reaches an explain call
    assert db_session.query(AIRequest).count() == 1


def test_ungrounded_answer_is_rejected_by_the_guardrail(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _canned_response(json.dumps({"intent": "financial_performance", "period": "default_recent", "metric": None}))
        # An invented number nowhere in the real financial-performance data.
        return _canned_response("Revenue was an incredible €9,999,999.99 this period!")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW
    )

    assert result.grounded is False
    assert "couldn't confidently answer" in result.answer


def test_network_failure_degrades_gracefully(db_session, business_id, monkeypatch):
    def _raise(*args, **kwargs):
        from app.ai.exceptions import AIProviderError

        raise AIProviderError("connection refused")

    monkeypatch.setattr(client, "chat_completion", _raise)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW
    )

    # The classify call itself failed — this must be told apart from a
    # genuine "the model decided this is out of scope" (real bug, found
    # live: hitting OpenRouter's daily rate limit made every question,
    # including perfectly in-scope ones, come back with the generic
    # "I can't help with that topic" message instead of an honest
    # "temporarily unavailable" one).
    assert result.intent == "provider_unavailable"
    assert result.grounded is False
    assert "temporarily unavailable" in result.answer
    row = db_session.query(AIRequest).one()
    assert row.success is False


def test_daily_usage_cap_blocks_further_ai_calls(db_session, business_id, monkeypatch):
    # Reads the real configured limit rather than hardcoding a number —
    # this value has already changed once (30 -> 200 for the testing
    # phase, since the configured model is free-tier and costs this app
    # $0/call) and will change again for a real launch; the test should
    # track whatever it's actually set to, not assume a specific number.
    limit = get_settings().ai_daily_request_limit_per_business
    repo = AIRequestRepository(db_session)
    for _ in range(limit):
        repo.create(business_id=business_id, user_id="user-1", lane="business_qa", provider="openrouter", model="x")

    def _fail(*args, **kwargs):
        raise AssertionError("chat_completion should not be called once the daily cap is reached")

    monkeypatch.setattr(client, "chat_completion", _fail)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW
    )

    assert result.intent == "usage_limit_reached"
    assert "limit" in result.answer.lower()


# --- product_lookup / purchase_lookup / repair_lookup ----------------------
# Covers the 0/1/many-match dispatch shared by all three new lookup
# intents (app/ai/service.py::_dispatch_lookup) — the many-match and
# 0-match cases never reach an explain call (zero further AI cost, same
# tier as the existing out_of_scope/metric_definition zero-cost paths).


def test_product_lookup_with_one_match_reaches_the_explain_call(db_session, business_id, monkeypatch):
    ProductRepository(db_session).create(
        business_id=business_id, sku="CL-100", name="Chain Lube 100ml", cost_price=Decimal("2.50"), sell_price=Decimal("6.99")
    )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("product_lookup", search_term="Chain Lube")
        return _canned_response("Chain Lube 100ml (CL-100) currently has 0 units in stock.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much stock of Chain Lube do I have?", now=_NOW
    )

    assert result.intent == "product_lookup"
    assert result.grounded is True
    assert db_session.query(AIRequest).count() == 2  # classify + explain


def test_product_lookup_with_no_match_is_a_deterministic_zero_cost_answer(db_session, business_id, monkeypatch):
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        return _classify_response("product_lookup", search_term="Bottom Bracket")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much stock of Bottom Bracket do I have?", now=_NOW
    )

    assert result.intent == "product_lookup"
    assert result.grounded is True
    assert "couldn't find" in result.answer
    assert len(calls) == 1  # classify only — no explain call for a 0-match lookup


def test_product_lookup_with_several_matches_asks_which_one_deterministically(db_session, business_id, monkeypatch):
    ProductRepository(db_session).create(
        business_id=business_id, sku="CL-100", name="Chain Lube 100ml", cost_price=None, sell_price=None
    )
    ProductRepository(db_session).create(
        business_id=business_id, sku="CL-250", name="Chain Lube 250ml", cost_price=None, sell_price=None
    )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("product_lookup", search_term="Chain Lube")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much stock of Chain Lube do I have?", now=_NOW
    )

    assert result.intent == "product_lookup"
    assert "found several matching results" in result.answer
    assert "Chain Lube 100ml" in result.answer
    assert "Chain Lube 250ml" in result.answer
    assert db_session.query(AIRequest).count() == 1  # classify only


def test_product_lookup_without_a_search_term_falls_back_safely(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("product_lookup", search_term=None)

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Tell me about my product", now=_NOW
    )

    assert result.intent == "out_of_scope"


def test_purchase_lookup_by_reference_reaches_the_explain_call(db_session, business_id, monkeypatch):
    product = ProductRepository(db_session).create(
        business_id=business_id, sku="CL-100", name="Chain Lube", cost_price=None, sell_price=None
    )
    db_session.commit()
    InventoryMovementRepository(db_session).create(
        business_id=business_id, product_id=product.id, quantity_delta=24, reason="purchase",
        purchase_reference="PO-123-ABC", event_date=date(2026, 1, 2),
    )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("purchase_lookup", search_term="PO-123")
        return _canned_response("You ordered 24 units of Chain Lube under PO-123-ABC on 2026-01-02.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What did I order under PO-123?", now=_NOW
    )

    assert result.intent == "purchase_lookup"
    assert result.grounded is True


def test_purchase_lookup_with_no_match_is_a_deterministic_zero_cost_answer(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("purchase_lookup", search_term="PO-999-NOPE")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What did I order under PO-999?", now=_NOW
    )

    assert result.intent == "purchase_lookup"
    assert "couldn't find" in result.answer
    assert db_session.query(AIRequest).count() == 1


def test_repair_lookup_by_reference_reaches_the_explain_call(db_session, business_id, monkeypatch):
    ProductionEventRepository(db_session).create(
        business_id=business_id, event_type="repair", description="Full service", status="completed",
        opened_at=datetime(2026, 1, 3, tzinfo=timezone.utc), completed_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        labour_cost=Decimal("20.00"), price_charged=Decimal("89.99"), customer_id=None, performed_by_id=None,
        import_record_id=None, repair_reference="JOB-364",
    )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("repair_lookup", search_term="JOB-364")
        return _canned_response("Repair JOB-364 (Full service) was charged at €89.99.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much did repair JOB-364 cost?", now=_NOW
    )

    assert result.intent == "repair_lookup"
    assert result.grounded is True


def test_repair_lookup_with_no_match_is_a_deterministic_zero_cost_answer(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("repair_lookup", search_term="JOB-999")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much did repair JOB-999 cost?", now=_NOW
    )

    assert result.intent == "repair_lookup"
    assert "couldn't find" in result.answer


# --- explicit_date period ---------------------------------------------------


def test_explicit_date_question_resolves_to_a_specific_day_and_reaches_the_explain_call(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("financial_performance", period="explicit_date", start_date="2026-01-04")
        return _canned_response("Your revenue on 2026-01-04 was €0.00 — no sales were recorded that day.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much was my revenue on the 4th of January?", now=_NOW
    )

    assert result.intent == "financial_performance"
    assert result.grounded is True


def test_explicit_date_with_an_unparseable_date_falls_back_to_default_recent_instead_of_failing(
    db_session, business_id, monkeypatch
):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("financial_performance", period="explicit_date", start_date="not-a-real-date")
        return _canned_response("Your gross margin coverage is 0% right now — no cost data has been recorded yet.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much was my revenue on the 4th of January?", now=_NOW
    )

    # Falls back to a normal, still-grounded answer rather than erroring —
    # exactly the same "fail closed to a safe default" posture as an
    # unrecognized plain period value already had.
    assert result.intent == "financial_performance"
    assert result.grounded is True
