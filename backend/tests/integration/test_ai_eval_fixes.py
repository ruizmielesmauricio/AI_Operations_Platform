"""Integration coverage for the deterministic fixes the ORLA-91 Ask ORLA
eval drove (tests/ai_eval/) — real SQLite DB, AI calls monkeypatched, same
style as test_ai_chat.py."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.ai import client
from app.ai.service import answer_question
from app.models.business import Business
from app.models.membership import Membership
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.inventory_movement import InventoryMovementRepository

_NOW = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def _canned(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {}, "model": "test-model"}


def _sell(db_session, business_id, product, *, quantity: int, unit_price: str, when: datetime) -> None:
    total = Decimal(unit_price) * quantity
    sale = Sale(business_id=business_id, sold_at=when, total_amount=total, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            business_id=business_id, sale_id=sale.id, product_id=product.id, quantity=quantity,
            unit_price=Decimal(unit_price), cost_price_at_sale=None,
        )
    )
    db_session.commit()


def _capture_explain_context(monkeypatch, classify: dict, answer: str) -> list[dict]:
    contexts: list[dict] = []

    def _fake(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _canned(json.dumps({"intents": [classify]}))
        contexts.append(json.loads(messages[0]["content"].split("DATA:\n", 1)[1].split("\n", 1)[1]))
        return _canned(answer)

    monkeypatch.setattr(client, "chat_completion", _fake)
    return contexts


def test_product_lookup_carries_the_products_own_sales_for_the_period(db_session, business_id, monkeypatch):
    tube = Product(business_id=business_id, sku="CP-3001", name="Inner Tube 29x2.2", sell_price=Decimal("8.99"))
    other = Product(business_id=business_id, sku="CP-3002", name="Brake Pads", sell_price=Decimal("16.99"))
    db_session.add_all([tube, other])
    db_session.commit()
    _sell(db_session, business_id, tube, quantity=3, unit_price="8.99", when=_NOW - timedelta(days=2))
    _sell(db_session, business_id, tube, quantity=2, unit_price="8.99", when=_NOW - timedelta(days=40))  # outside
    _sell(db_session, business_id, other, quantity=7, unit_price="16.99", when=_NOW - timedelta(days=1))

    contexts = _capture_explain_context(
        monkeypatch, {"intent": "product_lookup", "search_term": "Inner Tube"}, "You sold 3 Inner Tube 29x2.2 for €26.97."
    )
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How many Inner Tube did I sell?", now=_NOW
    )

    assert result.grounded is True
    assert result.answer.startswith("You sold 3 Inner Tube")
    sales = contexts[0]["sales"]
    assert sales["units_sold"] == 3
    assert sales["revenue"] == "26.97"
    assert sales["period"].startswith("Sun 7 Dec 2025 to Mon 5 Jan 2026")


def test_category_breakdown_context_has_all_category_totals(db_session, business_id, monkeypatch):
    product = Product(business_id=business_id, sku=None, name="Helmet", cost_price=Decimal("30.00"))
    db_session.add(product)
    db_session.commit()
    InventoryMovementRepository(db_session).create(
        business_id=business_id, product_id=product.id, quantity_delta=4, reason="purchase",
        event_date=(_NOW - timedelta(days=3)).date(), unit_cost=Decimal("30.00"),
    )
    db_session.commit()

    contexts = _capture_explain_context(
        monkeypatch, {"intent": "category_breakdown", "period": "default_recent"}, "You spent €120.00 on stock in total."
    )
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much did I spend on stock in total?",
        now=_NOW,
    )

    assert result.grounded is True
    totals = contexts[0]["totals_all_categories"]
    assert totals["spent_buying_stock"] == "120.00"
    assert "value_of_stock_on_hand_at_sell_price" in totals and "expenses" not in totals


def test_revenue_last_month_context_names_the_asked_period_and_the_comparison(db_session, business_id, monkeypatch):
    product = Product(business_id=business_id, sku=None, name="Chain", sell_price=Decimal("10.00"))
    db_session.add(product)
    db_session.commit()
    _sell(db_session, business_id, product, quantity=1, unit_price="10.00", when=datetime(2025, 12, 10, tzinfo=timezone.utc))

    contexts = _capture_explain_context(
        monkeypatch, {"intent": "financial_performance", "period": "last_completed_month"},
        "Revenue from 1 Dec 2025 to 31 Dec 2025 was €10.00.",
    )
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What was my revenue last month?", now=_NOW
    )

    assert result.grounded is True
    context = contexts[0]
    assert context["period_asked_about"].startswith("Mon 1 Dec 2025 to Wed 31 Dec 2025")
    # No comparison asked for, so no comparison figure to mistake for it.
    assert context["revenue"] == {"current": "10.00"}


def test_a_comparison_question_gets_the_labelled_comparison_period(db_session, business_id, monkeypatch):
    contexts = _capture_explain_context(
        monkeypatch, {"intent": "financial_performance", "period": "last_completed_month"}, "Both were 0.00."
    )
    answer_question(
        db_session, business_id=business_id, user_id="user-1",
        question="What did I make last month compared with the month before?", now=_NOW,
    )

    revenue = contexts[0]["revenue"]
    assert revenue["comparison_period"].startswith("Fri 31 Oct 2025 to Sun 30 Nov 2025")
    assert "comparison_period_revenue" in revenue and "previous" not in revenue


def test_naming_a_branch_whose_name_contains_the_parents_answers_for_the_branch(db_session, business_id, monkeypatch):
    parent = db_session.get(Business, business_id)
    branch = Business(name=f"{parent.name} Cork", template=parent.template, timezone=parent.timezone, parent_business_id=parent.id)
    db_session.add(branch)
    db_session.flush()
    db_session.add(Membership(business_id=branch.id, user_id="user-1", role="owner"))
    db_session.add(Membership(business_id=parent.id, user_id="user-1", role="owner"))
    db_session.commit()
    product = Product(business_id=parent.id, sku=None, name="Chain", sell_price=Decimal("50.00"))
    db_session.add(product)
    db_session.commit()
    _sell(db_session, parent.id, product, quantity=1, unit_price="50.00", when=_NOW - timedelta(days=1))

    contexts = _capture_explain_context(
        monkeypatch, {"intent": "financial_performance", "period": "default_recent"}, "Cork had no sales: €0.00."
    )
    answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much revenue did the Cork branch make?",
        now=_NOW,
    )

    assert contexts[0]["revenue"]["current"] == "0.00"


def test_pronoun_lookup_after_a_reorder_answer_continues_the_forecast(db_session, business_id, monkeypatch):
    contexts = _capture_explain_context(
        monkeypatch, {"intent": "product_lookup", "search_term": "those"}, "Nothing needs reordering yet."
    )
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Which one of those is the most urgent?",
        now=_NOW, previous_question="What should I reorder?", previous_answer="Nothing needs reordering yet.",
        previous_intent="forecast", previous_intents=["forecast"],
    )

    assert result.intent == "forecast"
    assert "horizon_days" in contexts[0]


def test_pronoun_lookup_without_a_previous_topic_is_left_alone(db_session, business_id, monkeypatch):
    _capture_explain_context(monkeypatch, {"intent": "product_lookup", "search_term": "those"}, "unused")
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How many of those do I have?", now=_NOW
    )

    assert result.intent == "product_lookup"
    assert "couldn't find anything" in result.answer


def test_is_pronoun_search_term():
    from app.ai.service import _is_pronoun_search_term

    assert _is_pronoun_search_term("those")
    assert _is_pronoun_search_term("Which one?")
    assert _is_pronoun_search_term("the most urgent")
    assert not _is_pronoun_search_term("Chain Lube")
    assert not _is_pronoun_search_term("PO-7009")
    assert not _is_pronoun_search_term(None)


def test_classify_gets_a_json_only_reminder_after_prior_turns(db_session, business_id, monkeypatch):
    seen: list[list[dict]] = []

    def _fake(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        seen.append(messages)
        return _canned(json.dumps({"intents": [{"intent": "out_of_scope"}]}))

    monkeypatch.setattr(client, "chat_completion", _fake)
    answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Tell me a joke.", now=_NOW,
        previous_question="What was revenue last week?", previous_answer="It was 10.00.", previous_intent="out_of_scope",
    )
    classify_messages = seen[0]
    assert classify_messages[-1]["role"] == "system"
    assert "Do not answer it" in classify_messages[-1]["content"]
    assert classify_messages[-2] == {"role": "user", "content": "Tell me a joke."}


def test_prose_classify_reply_to_a_month_follow_up_recovers_last_month(db_session, business_id, monkeypatch):
    product = Product(business_id=business_id, sku=None, name="Chain", sell_price=Decimal("10.00"))
    db_session.add(product)
    db_session.commit()
    _sell(db_session, business_id, product, quantity=1, unit_price="10.00", when=datetime(2025, 12, 10, tzinfo=timezone.utc))
    contexts: list[dict] = []

    def _fake(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _canned("Your revenue for the month before was 32,854.17.")  # prose, not JSON
        contexts.append(json.loads(messages[0]["content"].split("DATA:\n", 1)[1].split("\n", 1)[1]))
        return _canned("The comparison period had 0.00.")

    monkeypatch.setattr(client, "chat_completion", _fake)
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="And the month before?", now=_NOW,
        previous_question="What was my revenue last month?", previous_answer="It was 10.00.",
        previous_intent="financial_performance", previous_intents=["financial_performance"],
    )

    assert result.intent == "financial_performance"
    assert contexts[0]["period_asked_about"].startswith("Mon 1 Dec 2025 to Wed 31 Dec 2025")


def test_branch_split_follow_up_to_an_all_branches_question_stays_combined(db_session, business_id, monkeypatch):
    parent = db_session.get(Business, business_id)
    branch = Business(name="Northside", template=parent.template, timezone=parent.timezone, parent_business_id=parent.id)
    db_session.add(branch)
    db_session.flush()
    db_session.add_all([
        Membership(business_id=branch.id, user_id="user-1", role="owner"),
        Membership(business_id=parent.id, user_id="user-1", role="owner"),
    ])
    db_session.commit()

    contexts = _capture_explain_context(
        monkeypatch, {"intent": "financial_performance", "period": "default_recent"}, "Both branches had 0.00."
    )
    answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Split that by branch.", now=_NOW,
        previous_question="What is my revenue across all branches?", previous_answer="0.00.",
        previous_intent="financial_performance",
    )

    assert {b["business_name"] for b in contexts[0]["branches"]} == {parent.name, "Northside"}


def test_multi_line_purchase_lookup_supplies_the_line_count(db_session, business_id, monkeypatch):
    first = Product(business_id=business_id, sku=None, name="Helmet")
    second = Product(business_id=business_id, sku=None, name="Lock")
    db_session.add_all([first, second])
    db_session.commit()
    for product, qty in ((first, 4), (second, 2)):
        InventoryMovementRepository(db_session).create(
            business_id=business_id, product_id=product.id, quantity_delta=qty, reason="purchase",
            purchase_reference="PO-1", event_date=_NOW.date(),
        )
    db_session.commit()

    contexts = _capture_explain_context(
        monkeypatch, {"intent": "purchase_lookup", "search_term": "PO-1"}, "PO-1 had 2 lines: 4 Helmet and 2 Lock."
    )
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What did I order under PO-1?", now=_NOW
    )

    assert result.grounded is True
    assert contexts[0]["number_of_lines"] == 2


def test_empty_classify_reply_is_a_provider_failure_not_a_refusal(db_session, business_id, monkeypatch):
    monkeypatch.setattr(client, "chat_completion", lambda **kwargs: _canned(""))
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="Do I have any dead stock?", now=_NOW
    )

    assert result.intent == "provider_unavailable"
    assert "temporarily unavailable" in result.answer


def test_empty_classify_reply_to_a_follow_up_is_still_recovered(db_session, business_id, monkeypatch):
    def _fake(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _canned("")
        return _canned("The comparison period had 0.00.")

    monkeypatch.setattr(client, "chat_completion", _fake)
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="And the month before?", now=_NOW,
        previous_question="What was my revenue last month?", previous_answer="It was 0.00.",
        previous_intent="financial_performance",
    )

    assert result.intent == "financial_performance"


def test_invoice_reference_classified_as_a_repair_is_answered_as_the_purchase(db_session, business_id, monkeypatch):
    product = Product(business_id=business_id, sku=None, name="Inner Tube")
    db_session.add(product)
    db_session.commit()
    InventoryMovementRepository(db_session).create(
        business_id=business_id, product_id=product.id, quantity_delta=100, reason="purchase",
        purchase_reference="INV-2026-1188", event_date=_NOW.date(),
    )
    db_session.commit()

    contexts = _capture_explain_context(
        monkeypatch, {"intent": "repair_lookup", "search_term": "INV-2026-1188"}, "Invoice INV-2026-1188: 100 Inner Tube."
    )
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="What was on invoice INV-2026-1188?", now=_NOW
    )

    assert result.intent == "purchase_lookup"
    assert contexts[0]["quantity_received"] == 100


def test_a_reference_found_nowhere_keeps_the_classified_lookup(db_session, business_id, monkeypatch):
    _capture_explain_context(monkeypatch, {"intent": "repair_lookup", "search_term": "JOB-0000"}, "unused")
    result = answer_question(
        db_session, business_id=business_id, user_id="user-1", question="How much did JOB-0000 cost?", now=_NOW
    )

    assert result.intent == "repair_lookup"
    assert "couldn't find anything" in result.answer
