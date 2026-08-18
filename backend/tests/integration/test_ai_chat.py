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


def test_product_lookup_matches_across_a_non_ascii_dash_variant_in_the_search_term(
    db_session, business_id, monkeypatch
):
    # Live-reproduced real bug, exact reported transcript: "How many
    # E‑Motion Trail 500 did I order last time?" used U+2011 (NON-
    # BREAKING HYPHEN) where the stored product name has a plain ASCII
    # "-", and the product genuinely existed — a byte-exact match found
    # nothing. search_term here is deliberately the classify step's own
    # verbatim echo of the question's actual character, not a "clean"
    # ASCII stand-in — this is what a real free-tier model extraction
    # would hand back.
    ProductRepository(db_session).create(
        business_id=business_id, sku="EM-500", name="E-Motion Trail 500", cost_price=Decimal("450.00"),
        sell_price=Decimal("899.00"),
    )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("product_lookup", search_term="E‑Motion Trail 500")
        return _canned_response("E-Motion Trail 500 (EM-500) currently has 0 units in stock.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How much stock of E‑Motion Trail 500 do I have?", now=_NOW,
    )

    assert result.intent == "product_lookup"
    assert result.grounded is True
    assert "couldn't find" not in result.answer


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


def test_purchase_lookup_with_no_product_or_reference_match_never_leaks_unrelated_purchases(
    db_session, business_id, monkeypatch
):
    # Live-reproduced real bug: with an empty business, the existing
    # "no match" test above passed for the wrong reason — there was
    # nothing in the business at all for a broken fallback to leak. Here,
    # a real unrelated product/purchase exists, and the search term
    # ("E-Motion Trail 500") matches neither a purchase reference nor any
    # real product — this must still come back as a clean "not found,"
    # never silently fall through to an unscoped list of whatever else
    # was purchased (previously mislabelled as a "found several matching
    # results" disambiguation for products that were never a match at
    # all).
    product = ProductRepository(db_session).create(
        business_id=business_id, sku="CL-100", name="Chain Lube", cost_price=None, sell_price=None
    )
    db_session.commit()
    InventoryMovementRepository(db_session).create(
        business_id=business_id, product_id=product.id, quantity_delta=6, reason="purchase",
        purchase_reference="PO-CHAINLUBE", event_date=date(2026, 1, 2),
    )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("purchase_lookup", search_term="E-Motion Trail 500")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How many E-Motion Trail 500 did I order last time?", now=_NOW,
    )

    assert result.intent == "purchase_lookup"
    assert "couldn't find" in result.answer
    assert "Chain Lube" not in result.answer
    assert db_session.query(AIRequest).count() == 1  # never reached the explain call


def test_purchase_lookup_search_term_matching_several_products_asks_which_one_instead_of_reporting_not_found(
    db_session, business_id, monkeypatch
):
    # Live-reproduced real bug, found immediately after the fix above:
    # find_purchases's own "search term matched several products, which
    # one?" branch (app/application/lookups.py) populates match_labels
    # but leaves matches empty (no single resolved purchase record yet)
    # — _dispatch_lookup used to key its 0/1/many decision off `matches`
    # alone, so this genuinely-ambiguous case was misreported as "I
    # couldn't find anything matching," the opposite of what happened.
    product_a = ProductRepository(db_session).create(
        business_id=business_id, sku="EM-500", name="E-Motion Trail 500", cost_price=None, sell_price=None
    )
    product_b = ProductRepository(db_session).create(
        business_id=business_id, sku="EM-500-2", name="E-Motion Trail 500 2", cost_price=None, sell_price=None
    )
    db_session.commit()
    movement_repo = InventoryMovementRepository(db_session)
    movement_repo.create(
        business_id=business_id, product_id=product_a.id, quantity_delta=4, reason="purchase",
        purchase_reference="PO-EM500-A", event_date=date(2026, 1, 3),
    )
    movement_repo.create(
        business_id=business_id, product_id=product_b.id, quantity_delta=2, reason="purchase",
        purchase_reference="PO-EM500-B", event_date=date(2026, 1, 4),
    )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("purchase_lookup", search_term="E-Motion Trail 500")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How many E-Motion Trail 500 did I order last time?", now=_NOW,
    )

    assert result.intent == "purchase_lookup"
    assert "couldn't find" not in result.answer
    assert "found several matching results" in result.answer
    assert "E-Motion Trail 500" in result.answer
    assert "E-Motion Trail 500 2" in result.answer
    assert db_session.query(AIRequest).count() == 1  # zero-cost, never reached the explain call


def test_purchase_lookup_for_one_unambiguous_product_with_several_past_orders_answers_all_of_them(
    db_session, business_id, monkeypatch
):
    # Live-reproduced real bug, a different transcript from the one
    # above: "what did I order under E-Motion Trail 500 3?" named ONE
    # product with zero ambiguity (unlike the "500"/"500 2"/"500 3" case
    # above) — the product just happens to have several real past
    # orders. That's a complete multi-row answer, not a "which one did
    # you mean" situation; it used to be misreported as exactly that
    # disambiguation, listing the same product 5 times with no way to
    # actually get an answer out of it.
    product = ProductRepository(db_session).create(
        business_id=business_id, sku="EM-500-3", name="E-Motion Trail 500 3", cost_price=None, sell_price=None
    )
    db_session.commit()
    movement_repo = InventoryMovementRepository(db_session)
    for i, order_date in enumerate([date(2026, 2, 25), date(2026, 3, 10), date(2026, 5, 18)]):
        movement_repo.create(
            business_id=business_id, product_id=product.id, quantity_delta=2 + i, reason="purchase",
            purchase_reference=f"PO-2026-{i:03d}", event_date=order_date,
        )
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("purchase_lookup", search_term="E-Motion Trail 500 3")
        return _canned_response("You ordered E-Motion Trail 500 3 three times: on 2026-02-25, 2026-03-10, and 2026-05-18.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What did I order under E-Motion Trail 500 3?", now=_NOW,
    )

    assert result.intent == "purchase_lookup"
    assert "found several matching results" not in result.answer
    assert "which one" not in result.answer.lower()
    assert result.grounded is True
    assert db_session.query(AIRequest).count() == 2  # classify + explain — a real multi-row answer, not zero-cost


def test_purchase_lookup_last_order_phrasing_narrows_a_multi_order_history_to_just_the_most_recent(
    db_session, business_id, monkeypatch
):
    # Same real transcript, the direct follow-up: "...in my last order?"
    # — should narrow the same 3-order history down to just the most
    # recent row (2026-05-18), not repeat the full history.
    product = ProductRepository(db_session).create(
        business_id=business_id, sku="EM-500-3", name="E-Motion Trail 500 3", cost_price=None, sell_price=None
    )
    db_session.commit()
    movement_repo = InventoryMovementRepository(db_session)
    for i, order_date in enumerate([date(2026, 2, 25), date(2026, 3, 10), date(2026, 5, 18)]):
        movement_repo.create(
            business_id=business_id, product_id=product.id, quantity_delta=2 + i, reason="purchase",
            purchase_reference=f"PO-2026-{i:03d}", event_date=order_date,
        )
    db_session.commit()

    captured_context: dict = {}

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("purchase_lookup", search_term="E-Motion Trail 500 3")
        captured_context["system_prompt"] = messages[0]["content"]
        return _canned_response("Your last order of E-Motion Trail 500 3 was on 2026-05-18.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What did I order under E-Motion Trail 500 3 in my last order?", now=_NOW,
    )

    assert result.intent == "purchase_lookup"
    assert result.grounded is True
    # Only the single most-recent row's PO reference should have reached
    # the explain call — the two older orders were narrowed out before
    # the model ever saw them.
    assert "PO-2026-002" in captured_context["system_prompt"]  # 2026-05-18, i=2
    assert "PO-2026-000" not in captured_context["system_prompt"]  # 2026-02-25, i=0
    assert "PO-2026-001" not in captured_context["system_prompt"]  # 2026-03-10, i=1


def test_purchase_history_question_recovers_and_reaches_the_explain_call(db_session, business_id, monkeypatch):
    cheap = ProductRepository(db_session).create(
        business_id=business_id, sku="CH-1", name="Cheap Chain", cost_price=Decimal("2.00"), sell_price=None
    )
    expensive = ProductRepository(db_session).create(
        business_id=business_id, sku="EX-1", name="Expensive Hub", cost_price=Decimal("100.00"), sell_price=None
    )
    movement_repo = InventoryMovementRepository(db_session)
    movement_repo.create(
        business_id=business_id, product_id=cheap.id, quantity_delta=3, reason="purchase",
        purchase_reference="PO-CHEAP", event_date=date(2026, 1, 3), unit_cost=Decimal("9.00"),
    )
    movement_repo.create(
        business_id=business_id, product_id=expensive.id, quantity_delta=1, reason="purchase",
        purchase_reference="PO-EXP", event_date=date(2026, 1, 5), unit_cost=Decimal("100.00"),
    )
    db_session.commit()
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _classify_response("out_of_scope")
        return _canned_response("Your last order shown was Expensive Hub on 2026-01-05 at €100.00 per unit.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session,
        business_id=business_id,
        user_id="user-1",
        question="When were my last orders placed? and what were the most expensive things I ordered by unit?",
        now=_NOW,
    )

    assert result.intent == "purchase_history"
    assert result.grounded is True
    assert "Expensive Hub" in result.answer
    explain_prompt = calls[1][0]["content"]
    assert "recent_purchases" in explain_prompt
    assert "most_expensive_unit_purchases" in explain_prompt
    assert explain_prompt.index("Expensive Hub") < explain_prompt.index("Cheap Chain")


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


# --- last-exchange-only conversation memory ----------------------------
# Direct request: give ORLA memory of the immediately preceding question/
# answer only (never a full thread) so a follow-up like "what was the
# previous period?" can be resolved, without resending the whole
# conversation on every call.


def test_previous_exchange_is_threaded_into_both_classify_and_explain_as_prior_turns(
    db_session, business_id, monkeypatch
):
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _classify_response("financial_performance")
        return _canned_response("The previous period's revenue was €80,603.30, as I mentioned.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What was the previous period?", now=_NOW,
        previous_question="How's my revenue doing?",
        previous_answer="Your revenue was €49,986.73, down from €80,603.30 the period before.",
    )

    assert result.grounded is True  # the restated €80,603.30 must not be flagged as invented

    classify_messages, explain_messages = calls[0], calls[1]
    # Both calls carry the prior exchange as real user/assistant turns,
    # not spliced into the system prompt text.
    assert classify_messages[1] == {"role": "user", "content": "How's my revenue doing?"}
    assert classify_messages[2]["role"] == "assistant"
    assert classify_messages[3] == {"role": "user", "content": "What was the previous period?"}
    assert explain_messages[1] == {"role": "user", "content": "How's my revenue doing?"}
    assert explain_messages[2] == {
        "role": "assistant",
        "content": "Your revenue was €49,986.73, down from €80,603.30 the period before.",
    }
    assert explain_messages[3] == {"role": "user", "content": "What was the previous period?"}


def test_classify_call_truncates_the_previous_answer_but_explain_gets_the_full_text(
    db_session, business_id, monkeypatch
):
    long_previous_answer = "X" * 2000  # well past _CLASSIFY_PREVIOUS_ANSWER_MAX_CHARS (500)
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _classify_response("financial_performance")
        return _canned_response("Your revenue this period is €100.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Tell me more.", now=_NOW,
        previous_question="How's my revenue doing?", previous_answer=long_previous_answer,
    )

    classify_messages, explain_messages = calls[0], calls[1]
    assert len(classify_messages[2]["content"]) == 500
    assert len(explain_messages[2]["content"]) == 2000


def test_without_a_previous_exchange_the_messages_are_unchanged_from_before_memory_existed(
    db_session, business_id, monkeypatch
):
    # Regression guard — previous_question/previous_answer are optional
    # and both None by default; every question that isn't a follow-up
    # (including the very first one in a session) must produce the exact
    # same two-message shape as before this feature existed.
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _classify_response("financial_performance")
        return _canned_response("Your revenue this period is €100.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    answer_question(db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW)

    classify_messages, explain_messages = calls[0], calls[1]
    assert len(classify_messages) == 2
    assert len(explain_messages) == 2


def test_a_lone_previous_question_with_no_previous_answer_is_treated_as_no_prior_exchange(
    db_session, business_id, monkeypatch
):
    # Half-supplied memory (e.g. a frontend bug, or the very first
    # message where only one side could ever exist) must not produce a
    # malformed messages array — treated the same as no memory at all.
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _classify_response("financial_performance")
        return _canned_response("Your revenue this period is €100.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW,
        previous_question="Some earlier question", previous_answer=None,
    )

    classify_messages, explain_messages = calls[0], calls[1]
    assert len(classify_messages) == 2
    assert len(explain_messages) == 2


# --- deterministic period-follow-up recovery ----------------------------
# Live-verified real bug, reported three times with three different
# phrasings ("what was the previous period?", "when was the previous
# period?", "what is the last period?") — a prompt-only "infer the same
# intent as the previous turn" instruction held for the one exact
# phrasing it was tuned against and failed to generalise to the others
# on this free-tier model. Fixed with a deterministic recovery net, same
# shape as the reorder recovery above.


def test_period_follow_up_recovers_to_the_previous_turns_intent(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("out_of_scope")
        return _canned_response("The previous period ran from 20 to 26 July 2026.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What is the last period?", now=_NOW,
        previous_question="How's my revenue doing?", previous_answer="Your revenue was €100.00.",
        previous_intent="financial_performance",
    )

    assert result.intent == "financial_performance"


def test_aggregate_follow_up_recovers_to_the_previous_turns_intent(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("out_of_scope")
        return _canned_response("Merged together, the gross profit is €0.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Can you give me that as a merge?", now=_NOW,
        previous_question="Can you tell me the profit for my two branches?",
        previous_answer="Branch A had €0.00 gross profit and Branch B had €0.00 gross profit.",
        previous_intent="financial_performance",
    )

    assert result.intent == "financial_performance"
    assert result.grounded is True


def test_full_business_follow_up_recovers_to_the_previous_turns_intent(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("out_of_scope")
        return _canned_response("For the full business, gross profit is €0.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session,
        business_id=business_id,
        user_id="user-1",
        question="Can you show me this as a full business?",
        now=_NOW,
        previous_question="Can you tell me the profit for my two branches?",
        previous_answer="Branch A had €0.00 gross profit and Branch B had €0.00 gross profit.",
        previous_intent="financial_performance",
    )

    assert result.intent == "financial_performance"
    assert result.grounded is True


def test_period_follow_up_does_not_recover_without_a_previous_intent(db_session, business_id, monkeypatch):
    # No previous_intent at all (e.g. the very first question in a
    # session, or a page refresh that reset memory) — nothing to recover
    # to, must fall through to the same safe refusal as before.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("out_of_scope")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What is the last period?", now=_NOW
    )

    assert result.intent == "out_of_scope"


def test_period_follow_up_ignores_a_previous_intent_outside_the_continuable_allow_list(
    db_session, business_id, monkeypatch
):
    # previous_intent is untrusted client input — a value outside the
    # fixed allow-list (here, a lookup intent that shouldn't be blindly
    # continued) must never be used, even if a period-shaped question
    # was asked right after it.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("out_of_scope")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What is the last period?", now=_NOW,
        previous_question="How much Chain Lube do I have?", previous_answer="You have 12 units.",
        previous_intent="product_lookup",
    )

    assert result.intent == "out_of_scope"


def test_a_genuine_topic_change_after_a_continuable_intent_is_not_swallowed_by_recovery(
    db_session, business_id, monkeypatch
):
    # The recovery net only ever fires when the question itself looks
    # like a period follow-up — a question that doesn't match those
    # keywords, and that classify genuinely refuses, must stay refused
    # even with a perfectly valid previous_intent sitting right there.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("out_of_scope")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What's the weather like today?", now=_NOW,
        previous_question="How's my revenue doing?", previous_answer="Your revenue was €100.00.",
        previous_intent="financial_performance",
    )

    assert result.intent == "out_of_scope"


# --- multi-intent compound questions -----------------------------------
# Covers answer_question's part-based assembly for a question that asks
# more than one distinct thing ("what's my revenue and what should I
# reorder") — still exactly 2 AI calls (classify + explain) regardless of
# how many parts, per-part grounding, and a part that can't be answered
# disclosing that instead of discarding the whole response. The
# overwhelming single-intent case is covered exhaustively by every other
# test in this file; these are specifically the composition behavior.


def _intent_obj(intent: str, **extra) -> dict:
    payload = {"intent": intent, "period": None, "metric": None}
    payload.update(extra)
    return payload


def _multi_classify_response(*intent_objs: dict) -> dict:
    return _canned_response(json.dumps({"intents": list(intent_objs)}))


def test_compound_question_across_two_lanes_merges_both_parts_into_one_grounded_answer(
    db_session, business_id, monkeypatch
):
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _multi_classify_response(_intent_obj("financial_performance"), _intent_obj("forecast"))
        return _canned_response(
            "⟦PART_1⟧Your gross margin coverage is low right now — no cost data has been recorded yet."
            "\n⟦PART_2⟧Nothing is projected to run out of stock soon based on your current sales rate."
        )

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How's my revenue doing, and what should I reorder soon?", now=_NOW,
    )

    assert len(calls) == 2  # classify, then one shared explain call — never one per part
    assert result.intents == ("financial_performance", "forecast")
    assert result.intent == "financial_performance"
    assert result.grounded is True
    assert "gross margin coverage is low" in result.answer
    assert "run out of stock soon" in result.answer
    assert "⟦" not in result.answer  # markers are never shown to the user
    assert db_session.query(AIRequest).count() == 2


def test_one_part_fails_grounding_the_other_part_is_still_answered(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _multi_classify_response(_intent_obj("financial_performance"), _intent_obj("forecast"))
        return _canned_response(
            "⟦PART_1⟧Your gross margin coverage is low right now — no cost data has been recorded yet."
            "\n⟦PART_2⟧You should reorder 9999999 units immediately."  # invented number, not in any context
        )

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How's my revenue doing, and what should I reorder soon?", now=_NOW,
    )

    assert result.grounded is False  # at least one part fell back
    assert "gross margin coverage is low" in result.answer  # the good part survives
    assert "9999999" not in result.answer  # the invented claim never reaches the user
    assert result.intents == ("financial_performance", "forecast")


def test_one_part_with_no_available_data_is_disclosed_the_other_part_still_answers(
    db_session, business_id, monkeypatch
):
    from app.models.business import Business

    # workshop_performance is only available for the bicycle_shop
    # template — a non-bike-shop business gets None context for it,
    # resolved deterministically with zero AI cost (see _build_part).
    non_bike_business = Business(name="Not A Bike Shop", template="generic_retail")
    db_session.add(non_bike_business)
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _multi_classify_response(_intent_obj("financial_performance"), _intent_obj("workshop_performance"))
        # Only one marker: the workshop part never reaches the model at
        # all (it was already resolved before the explain call).
        return _canned_response(
            "⟦PART_1⟧Your gross margin coverage is low right now — no cost data has been recorded yet."
        )

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=non_bike_business.id, user_id="user-1",
        question="How's my revenue doing, and how's the workshop doing?", now=_NOW,
    )

    assert result.grounded is True  # the one AI part was grounded; the other was never a guess
    assert "gross margin coverage is low" in result.answer
    assert result.intents == ("financial_performance", "workshop_performance")
    assert db_session.query(AIRequest).count() == 2  # still just classify + explain, not 3


def test_lookup_zero_match_mixed_with_an_aggregate_intent_still_answers_the_other_part(
    db_session, business_id, monkeypatch
):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _multi_classify_response(
                _intent_obj("product_lookup", search_term="Nonexistent Widget"), _intent_obj("financial_performance")
            )
        return _canned_response(
            "⟦PART_1⟧Your gross margin coverage is low right now — no cost data has been recorded yet."
        )

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How much stock of Nonexistent Widget do I have, and how's my revenue doing?", now=_NOW,
    )

    assert 'find anything matching "Nonexistent Widget"' in result.answer
    assert "gross margin coverage is low" in result.answer
    assert result.intents == ("product_lookup", "financial_performance")


def test_marker_split_failure_falls_back_to_a_coarse_whole_answer_grounding_check(
    db_session, business_id, monkeypatch
):
    # The model ignores the marker instruction entirely and just writes
    # plain prose — a real possibility given free-tier model variance
    # (see _split_multi_part_answer's own docstring). No markers at all
    # means the parts can't be told apart, so this falls back to one
    # whole-answer guardrail check instead of a misattributed split.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _multi_classify_response(_intent_obj("financial_performance"), _intent_obj("forecast"))
        return _canned_response(
            "Your gross margin coverage is low right now, and nothing is projected to run out of stock soon."
        )

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How's my revenue doing, and what should I reorder soon?", now=_NOW,
    )

    assert result.grounded is True
    assert "gross margin coverage is low" in result.answer
    assert result.intents == ("financial_performance", "forecast")


def test_marker_split_failure_with_an_ungrounded_answer_falls_back_to_the_safe_message(
    db_session, business_id, monkeypatch
):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _multi_classify_response(_intent_obj("financial_performance"), _intent_obj("forecast"))
        return _canned_response("You should reorder 9999999 units immediately.")  # no markers, invented number

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="How's my revenue doing, and what should I reorder soon?", now=_NOW,
    )

    assert result.grounded is False
    assert "9999999" not in result.answer


def test_single_intent_question_shape_is_unchanged_by_multi_intent_support(db_session, business_id, monkeypatch):
    # Explicit regression guard: intents is a length-1 tuple matching
    # intent, and no marker artifact ever leaks into a plain single-
    # question answer — the byte-for-byte-identical single-intent path
    # this module's own docstrings promise.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("financial_performance")  # bare object, not an "intents" array
        return _canned_response("Your gross margin coverage is 0% right now — no cost data has been recorded yet.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How's my revenue doing?", now=_NOW
    )

    assert result.intents == ("financial_performance",)
    assert result.intent == "financial_performance"
    assert "⟦" not in result.answer
    assert "part_1" not in result.answer.lower()


def test_previous_intents_plural_recovers_a_follow_up_against_a_non_first_part(
    db_session, business_id, monkeypatch
):
    # The previous turn was itself compound (product_lookup + forecast) —
    # previous_intent alone (the first part, "product_lookup") isn't
    # continuable, but previous_intents carries "forecast" too, which is.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("out_of_scope")
        return _canned_response("The previous period's reorder picture looked about the same.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What about the previous period?", now=_NOW,
        previous_question="How much Chain Lube do I have, and what should I reorder?",
        previous_answer="You have 12 units of Chain Lube. Nothing needs reordering right now.",
        previous_intent="product_lookup", previous_intents=["product_lookup", "forecast"],
    )

    assert result.intent == "forecast"


# --- weather_pattern_lookup / weather_outlook -------------------------------
# Covers the two new Ask ORLA weather intents (app/ai/service.py::
# _dispatch_weather_category_lookup, and the direct weather_outlook branch
# in _build_part) — the compliance boundary (no raw Met Éireann figure ever
# reaching a chat answer) is already enforced structurally, since neither
# code path ever puts a rain_mm/temp_mean_c/wind_speed_kph value into
# context; these tests cover the 0/1/many dispatch and zero-cost paths.

from app.models.business import Business as _Business
from app.models.product import Product as _Product
from app.models.product import ProductCategory as _ProductCategory
from app.models.sale import Sale as _Sale
from app.models.sale import SaleItem as _SaleItem
from app.models.weather_observation import WeatherObservation as _WeatherObservation
from app.weather import client as weather_client


def _set_weather_coordinates(db_session, business_id):
    business = db_session.get(_Business, business_id)
    business.latitude = Decimal("53.3806")
    business.longitude = Decimal("-6.1750")
    db_session.commit()
    return business


def _seed_weather_pattern_history(db_session, business_id, *, category_name, anchor_today):
    """Same 12-rainy/28-dry, 40-day shape as tests/integration/
    test_weather_insights.py's own fixture — enough to clear both the
    sample-size and materiality gates in app/analytics/weather_patterns.py."""
    from datetime import timedelta

    category = _ProductCategory(business_id=business_id, name=category_name)
    db_session.add(category)
    db_session.flush()

    start = anchor_today - timedelta(days=40)
    for offset in range(40):
        day = start + timedelta(days=offset)
        rainy = offset < 12
        db_session.add(
            _WeatherObservation(
                business_id=business_id, observed_date=day,
                rain_mm=Decimal("5") if rainy else Decimal("0"),
                temp_mean_c=Decimal("15"), temp_min_c=Decimal("15"), temp_max_c=Decimal("15"),
                wind_speed_kph=Decimal("10"),
            )
        )
        product = _Product(
            business_id=business_id, sku=None, name=f"Item {offset}", category_id=category.id,
            cost_price=Decimal("5.00"), sell_price=Decimal("10.00"),
        )
        db_session.add(product)
        db_session.flush()
        sale = _Sale(
            business_id=business_id, sold_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
            total_amount=Decimal("10.00") * (10 if rainy else 2), order_reference=None,
        )
        db_session.add(sale)
        db_session.flush()
        db_session.add(
            _SaleItem(
                business_id=business_id, sale_id=sale.id, product_id=product.id,
                quantity=10 if rainy else 2, unit_price=Decimal("10.00"), cost_price_at_sale=Decimal("5.00"),
            )
        )
        db_session.flush()
    db_session.commit()
    return category


def test_weather_pattern_lookup_with_one_match_and_real_history_reaches_the_explain_call(
    db_session, business_id, monkeypatch
):
    _set_weather_coordinates(db_session, business_id)
    _seed_weather_pattern_history(db_session, business_id, category_name="Waterproof Gear", anchor_today=_NOW.date())

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("weather_pattern_lookup", search_term="Waterproof")
        return _canned_response(
            "Rainy days have historically meant more demand for Waterproof Gear, based on your own sales history."
        )

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="Does weather affect sales of Waterproof Gear?", now=_NOW,
    )

    assert result.intent == "weather_pattern_lookup"
    assert result.grounded is True
    assert db_session.query(AIRequest).count() == 2  # classify + explain


def test_weather_pattern_lookup_with_no_matching_category_names_real_categories(
    db_session, business_id, monkeypatch
):
    from app.repositories.product import ProductCategoryRepository

    ProductCategoryRepository(db_session).create(business_id=business_id, name="Tyres & Tubes")
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("weather_pattern_lookup", search_term="Sunglasses")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="Does weather affect sales of Sunglasses?", now=_NOW,
    )

    assert result.intent == "weather_pattern_lookup"
    assert result.grounded is True
    assert "couldn't find" in result.answer
    assert "Tyres & Tubes" in result.answer
    assert db_session.query(AIRequest).count() == 1  # classify only


def test_weather_pattern_lookup_with_several_matching_categories_asks_which_one(
    db_session, business_id, monkeypatch
):
    from app.repositories.product import ProductCategoryRepository

    ProductCategoryRepository(db_session).create(business_id=business_id, name="Locks")
    ProductCategoryRepository(db_session).create(business_id=business_id, name="Lock Oil")
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("weather_pattern_lookup", search_term="Lock")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="Does weather affect sales of Lock?", now=_NOW,
    )

    assert result.intent == "weather_pattern_lookup"
    assert "found several matching categories" in result.answer
    assert "Locks" in result.answer and "Lock Oil" in result.answer
    assert db_session.query(AIRequest).count() == 1  # classify only


def test_weather_pattern_lookup_resolved_category_with_no_weather_history_yet(db_session, business_id, monkeypatch):
    from app.repositories.product import ProductCategoryRepository

    ProductCategoryRepository(db_session).create(business_id=business_id, name="Scooters")
    db_session.commit()

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("weather_pattern_lookup", search_term="Scooters")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="Does weather affect sales of Scooters?", now=_NOW,
    )

    assert result.intent == "weather_pattern_lookup"
    assert "don't have enough weather history" in result.answer
    assert db_session.query(AIRequest).count() == 1  # classify only


def test_weather_pattern_lookup_without_a_search_term_falls_back_safely(db_session, business_id, monkeypatch):
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("weather_pattern_lookup", search_term=None)

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Does weather affect sales?", now=_NOW
    )

    assert result.intent == "out_of_scope"


def test_weather_outlook_with_a_matching_upcoming_forecast_reaches_the_explain_call(
    db_session, business_id, monkeypatch
):
    from app.weather.client import DailyForecast
    from datetime import timedelta

    business = _set_weather_coordinates(db_session, business_id)
    _seed_weather_pattern_history(db_session, business_id, category_name="Waterproof Gear", anchor_today=_NOW.date())

    forecast = [
        DailyForecast(
            day=_NOW.date() + timedelta(days=i), rain_mm=Decimal("5.00"), temp_mean_c=Decimal("10.00"),
            temp_min_c=Decimal("8.00"), temp_max_c=Decimal("12.00"), wind_speed_kph=Decimal("10.00"),
        )
        for i in range(7)
    ]
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: forecast)

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_response("weather_outlook")
        return _canned_response("Rain is forecast this week, which has historically meant more demand for Waterproof Gear.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What should I expect this week given the forecast?", now=_NOW,
    )

    assert result.intent == "weather_outlook"
    assert result.grounded is True
    assert db_session.query(AIRequest).count() == 2  # classify + explain


def test_weather_outlook_with_nothing_notable_is_a_deterministic_zero_cost_answer(db_session, business_id, monkeypatch):
    # No coordinates resolved at all -- get_weather_pattern_findings
    # degrades to [] gracefully, same as everywhere else it's called.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("weather_outlook")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What should I expect this week given the forecast?", now=_NOW,
    )

    assert result.intent == "weather_outlook"
    assert result.grounded is True
    assert "Nothing weather-notable" in result.answer
    assert db_session.query(AIRequest).count() == 1  # classify only


def test_weather_outlook_recovers_on_a_vague_follow_up_but_weather_pattern_lookup_does_not(
    db_session, business_id, monkeypatch
):
    # weather_outlook is in _CONTINUABLE_INTENTS (a forward-looking intent
    # a vague period follow-up can safely re-run); weather_pattern_lookup
    # deliberately is not (continuing it blindly would re-run a stale
    # category search term), same exclusion reasoning already documented
    # for product_lookup/purchase_lookup/repair_lookup. Uses the exact
    # same period-follow-up recovery net (_looks_like_a_period_follow_up_
    # question) already exercised for financial_performance elsewhere in
    # this file.
    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        return _classify_response("out_of_scope")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    recovered = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What about the previous period?", now=_NOW,
        previous_question="What should I expect this week given the forecast?",
        previous_answer="Nothing weather-notable stands out for the week ahead right now.",
        previous_intent="weather_outlook",
    )
    assert recovered.intent == "weather_outlook"

    not_recovered = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What about the previous period?", now=_NOW,
        previous_question="Does weather affect sales of Waterproof Gear?",
        previous_answer="I don't have enough weather history yet to say.",
        previous_intent="weather_pattern_lookup",
    )
    assert not_recovered.intent == "out_of_scope"
