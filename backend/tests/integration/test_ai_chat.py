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

    # The explain call's system prompt must actually carry both
    # governance layers — a disconnect here (e.g. someone rewrites the
    # DATA prefix and forgets to fold the files back in) would silently
    # strip every grounding/scope rule and the tone layer without any
    # other test noticing, since nothing else asserts on prompt content.
    explain_system_prompt = calls[1][0]["content"]
    assert "ORLA Constitution" in explain_system_prompt
    assert "ORLA Personality" in explain_system_prompt
    assert "DATA:" in explain_system_prompt


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


# --- category_breakdown -----------------------------------------------------
# Real gap found live: "what's my biggest cost/expense" questions had no
# intent to land in at all.


def test_category_breakdown_question_reaches_the_explain_call(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("category_breakdown")
        # A category_breakdown context with zero categories/products still
        # returns real (empty-list) JSON — echoes a fact that's always
        # true of it regardless of seeded data.
        return _canned_response("You don't have any product categories set up yet, so there's nothing to break down.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What's my biggest cost?", now=_NOW
    )

    assert result.intent == "category_breakdown"
    assert result.grounded is True


def test_category_breakdown_with_explicit_date_range(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response(
                "category_breakdown", period="explicit_date", start_date="2026-01-01", end_date="2026-01-31"
            )
        return _canned_response("You don't have any product categories set up yet, so there's nothing to break down.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What was my largest expense from 1 to 31 January?", now=_NOW,
    )

    assert result.intent == "category_breakdown"
    assert result.grounded is True


# --- out_of_scope -> forecast recovery --------------------------------------
# Real gap found live via a fire-test run: a reorder/stock-out-shaped
# question occasionally classified out_of_scope even though the classify
# prompt's own "forecast" description explicitly covers it.


def test_reorder_shaped_question_recovers_from_a_stray_out_of_scope_classification(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("out_of_scope")
        return _canned_response("No products need reordering right now — not enough sales history yet to forecast demand.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What is likely to run out of stock during the next two weeks?", now=_NOW,
    )

    assert result.intent == "forecast"


def test_a_genuinely_unrelated_question_still_falls_back_to_out_of_scope(db_session, business_id, monkeypatch):
    # Confirms the recovery above is narrowly scoped to reorder-shaped
    # language, not a general "trust the model less" loosening — a
    # question with no such keywords stays out_of_scope, zero AI cost.
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        return _classify_response("out_of_scope")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What's the weather like today?", now=_NOW
    )

    assert result.intent == "out_of_scope"
    assert len(calls) == 1  # classify only — the recovery never triggers a second AI call for a real refusal


# --- explain-step provider failure keeps the right intent -------------------
# Real bug found live: a provider failure during the *explain* call (as
# opposed to classify) was silently tagged with whatever intent had
# already been classified, instead of "provider_unavailable" — misleading
# for anything inspecting result.intent, even though the message shown to
# the user was already correct.


def test_explain_step_provider_failure_is_tagged_provider_unavailable_not_the_original_intent(
    db_session, business_id, monkeypatch
):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("financial_performance")
        from app.ai.exceptions import AIProviderError

        raise AIProviderError("connection refused")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW
    )

    assert result.intent == "provider_unavailable"
    assert result.grounded is False
    assert "temporarily unavailable" in result.answer


# --- forecast horizon_days threaded from the classify step -------------------
# Real bug found live via a fire-test run: "What is likely to run out of
# stock during the next two weeks?" always fetched the default 7-day
# forecast, so a correct answer naturally saying "14 days" had no matching
# horizon anywhere in the fetched context — the guardrail (rightly)
# rejected it. The fix is giving classify a way to name the actual horizon
# the question asked about, not loosening the guardrail.


def test_forecast_question_naming_a_timeframe_fetches_that_horizon_not_the_default(db_session, business_id, monkeypatch):
    import app.ai.service as service_module

    captured_kwargs = {}
    real_get_forecast = service_module.get_forecast

    def _spy_get_forecast(db, *, business_id, now=None, horizon_days=7, category_id=None):
        captured_kwargs["horizon_days"] = horizon_days
        return real_get_forecast(db, business_id=business_id, now=now, horizon_days=horizon_days, category_id=category_id)

    monkeypatch.setattr(service_module, "get_forecast", _spy_get_forecast)

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("forecast", horizon_days=14)
        return _canned_response("Nothing is projected to run out over the next 14 days based on your current sales rate.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What is likely to run out of stock during the next two weeks?", now=_NOW,
    )

    assert captured_kwargs["horizon_days"] == 14
    assert result.intent == "forecast"


def test_forecast_question_with_no_named_timeframe_uses_the_default_horizon(db_session, business_id, monkeypatch):
    import app.ai.service as service_module

    captured_kwargs = {}
    real_get_forecast = service_module.get_forecast

    def _spy_get_forecast(db, *, business_id, now=None, horizon_days=7, category_id=None):
        captured_kwargs["horizon_days"] = horizon_days
        return real_get_forecast(db, business_id=business_id, now=now, horizon_days=horizon_days, category_id=category_id)

    monkeypatch.setattr(service_module, "get_forecast", _spy_get_forecast)

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("forecast")  # no horizon_days at all
        return _canned_response("Nothing is projected to run out soon based on your current sales rate.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What should I reorder soon?", now=_NOW
    )

    assert captured_kwargs["horizon_days"] == 7


def test_forecast_horizon_days_out_of_range_falls_back_to_the_default(db_session, business_id, monkeypatch):
    import app.ai.service as service_module

    captured_kwargs = {}
    real_get_forecast = service_module.get_forecast

    def _spy_get_forecast(db, *, business_id, now=None, horizon_days=7, category_id=None):
        captured_kwargs["horizon_days"] = horizon_days
        return real_get_forecast(db, business_id=business_id, now=now, horizon_days=horizon_days, category_id=category_id)

    monkeypatch.setattr(service_module, "get_forecast", _spy_get_forecast)

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            # A hallucinated/malformed value (well past the API's own
            # ge=1, le=90 bound) must not be trusted as-is.
            return _classify_response("forecast", horizon_days=9999)
        return _canned_response("Nothing is projected to run out soon based on your current sales rate.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What should I reorder in the next 9999 days?", now=_NOW
    )

    assert captured_kwargs["horizon_days"] == 7


# --- guardrail: numbered-list markers in a multi-item answer -----------------
# Real bug found live via a fire-test run: "give me the five actions..."
# makes the explain prompt's own multi-item instruction kick in, and the
# model naturally writes "1. ... 2. ... 3. ..." — every one of those list
# markers parses as a Decimal and got wrongly flagged as an unsupported
# numeric claim, rejecting an otherwise fully-grounded answer.


def test_a_correct_numbered_list_answer_is_not_rejected_for_its_own_list_markers(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("findings_recommendations")
        return _canned_response(
            "Here are the top actions: 1. Reorder low-stock items soon. 2. Review your slowest-selling "
            "products. 3. Investigate any recent revenue changes."
        )

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="Give me the five actions I should take, ranked by impact.", now=_NOW,
    )

    assert result.intent == "findings_recommendations"
    assert result.grounded is True
