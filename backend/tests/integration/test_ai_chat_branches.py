"""Covers app/ai/service.py::answer_question's two branch-aware paths
against a real (SQLite) database, with the network call
(app.ai.client.chat_completion) monkeypatched — same style as
test_ai_chat.py. (1) all_branches=True combines a parent shop and its
branch into one answer. (2) A question naming one specific branch by
name always overrides whatever scope was otherwise selected — including
under all_branches=True.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from app.ai import client
from app.ai.service import answer_question
from app.models.business import Business
from app.models.membership import Membership
from app.models.product import Product
from app.models.sale import Sale, SaleItem

# Deliberately real wall-clock "now", not a fixed historical date — the
# classify default period ("default_recent") resolves its 30-day window
# via app/analytics/period.py::resolve_period's own `now` default
# (real time), independent of whatever `now` is passed into
# answer_question itself (that only threads through for the
# last_completed_week/month period types — see _resolve_dates). Seeded
# sales need to actually fall inside that real window to be counted.
_NOW = datetime.now(timezone.utc)


def _canned_response(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
        "model": "test-model",
    }


def _classify_financial_performance() -> dict:
    return _canned_response(json.dumps({"intent": "financial_performance", "period": "default_recent", "metric": None}))


def _make_sale(db_session, business_id, *, amount: Decimal):
    product = Product(business_id=business_id, sku=None, name="Chain Lube", cost_price=Decimal("5.00"))
    db_session.add(product)
    db_session.flush()
    sale = Sale(business_id=business_id, sold_at=_NOW, total_amount=amount, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            business_id=business_id, sale_id=sale.id, product_id=product.id, quantity=1, unit_price=amount,
            cost_price_at_sale=Decimal("5.00"),
        )
    )
    db_session.commit()


def _seed_group(db_session, *, branch_timezone: str = "Europe/Dublin"):
    parent = Business(name="Test Bike Shop", timezone="Europe/Dublin")
    branch = Business(name="Galway", timezone=branch_timezone)
    db_session.add_all([parent, branch])
    db_session.flush()
    branch.parent_business_id = parent.id
    db_session.add(Membership(business_id=parent.id, user_id="owner", role="owner"))
    db_session.add(Membership(business_id=branch.id, user_id="owner", role="owner"))
    db_session.commit()

    _make_sale(db_session, parent.id, amount=Decimal("100.00"))
    _make_sale(db_session, branch.id, amount=Decimal("300.00"))
    return parent, branch


def test_all_branches_combines_revenue_across_the_group(db_session, monkeypatch):
    parent, _branch = _seed_group(db_session)
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _classify_financial_performance()
        # Echo the number the explain call was actually given, so the
        # assertion below proves what context reached it, not just that
        # some answer came back.
        return _canned_response("Your combined revenue this period was €400.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    result = answer_question(
        db_session, business_id=parent.id, user_id="owner", question="How's my revenue doing?",
        now=_NOW, all_branches=True,
    )

    assert result.grounded is True
    assert "400.00" in result.answer


def test_naming_a_branch_directly_overrides_all_branches(db_session, monkeypatch):
    parent, branch = _seed_group(db_session)
    calls = []

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        calls.append(messages)
        if response_format is not None:
            return _classify_financial_performance()
        return _canned_response("Galway's revenue this period was €300.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    # all_branches=True AND the question names the branch directly — the
    # explicit name must win, giving Galway's own €300 rather than the
    # combined €400.
    result = answer_question(
        db_session, business_id=parent.id, user_id="owner", question="How is Galway doing?",
        now=_NOW, all_branches=True,
    )

    assert result.grounded is True
    assert "300.00" in result.answer


def test_naming_a_branch_directly_works_without_all_branches_too(db_session, monkeypatch):
    parent, branch = _seed_group(db_session)

    def _fake_chat_completion(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify_financial_performance()
        return _canned_response("Galway's revenue this period was €300.00.")

    monkeypatch.setattr(client, "chat_completion", _fake_chat_completion)

    # Browsing from the parent shop's own chat page, no all_branches flag
    # at all — naming Galway in the question is still enough on its own.
    result = answer_question(
        db_session, business_id=parent.id, user_id="owner", question="What did Galway make this week?", now=_NOW,
    )

    assert result.grounded is True
    assert "300.00" in result.answer


def test_all_branches_with_mismatched_timezones_is_a_zero_cost_refusal(db_session, monkeypatch):
    parent, _branch = _seed_group(db_session, branch_timezone="America/New_York")

    def _fail(*args, **kwargs):
        raise AssertionError("chat_completion should not be called when the group can't be combined")

    monkeypatch.setattr(client, "chat_completion", _fail)

    result = answer_question(
        db_session, business_id=parent.id, user_id="owner", question="How's my combined revenue doing?",
        now=_NOW, all_branches=True,
    )

    assert result.grounded is True
    assert "timezone" in result.answer.lower()


def test_all_branches_rejects_a_caller_missing_from_any_group_member(db_session, monkeypatch):
    parent, branch = _seed_group(db_session)
    # A manager added to the parent only, not the branch — the real
    # security property: combining must fail closed, not silently answer
    # using only the businesses this caller happens to have access to.
    db_session.add(Membership(business_id=parent.id, user_id="parent-only-manager", role="manager"))
    db_session.commit()

    def _fail(*args, **kwargs):
        raise AssertionError("chat_completion should not be called for an unauthorized group")

    monkeypatch.setattr(client, "chat_completion", _fail)

    result = answer_question(
        db_session, business_id=parent.id, user_id="parent-only-manager", question="How's my revenue doing?",
        now=_NOW, all_branches=True,
    )

    assert result.intent == "out_of_scope"
