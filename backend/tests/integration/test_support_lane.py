"""The conversational agent's support lane end to end (PR-5.7, ADR-020,
ADR-028): the classifier picks the lane, how-to answers come only from
retrieved help passages, and anything unanswerable becomes a handoff offer.
The network call (app.ai.client.chat_completion) is monkeypatched, same
style as test_ai_chat.py."""

import json
from datetime import datetime, timezone

from app.ai import client, support_lane
from app.ai.exceptions import AIProviderError
from app.ai.service import answer_question
from app.models.ai_request import AIRequest

_NOW = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
_STOCK_PASSAGE = "upload-stock-count#how-to-upload-a-stock-count"


def _canned(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001},
        "model": "test-model",
    }


def _classify(*intents: str) -> dict:
    return _canned(json.dumps({"intents": [{"intent": i, "period": None, "metric": None} for i in intents]}))


class _FakeProvider:
    """Records every call; answers the classify call (response_format=json
    with an "intents" prompt) and the support explain call separately."""

    def __init__(self, *, classify: dict, explain: dict | None = None, explain_error: bool = False):
        self.classify = classify
        self.explain = explain
        self.explain_error = explain_error
        self.calls: list[list[dict]] = []

    def __call__(self, *, messages, response_format=None, max_tokens=500, temperature=0.2):
        self.calls.append(messages)
        system = client.message_text(messages[0])
        if "intent classifier" in system:
            return self.classify
        if self.explain_error:
            raise AIProviderError("down")
        assert self.explain is not None, "unexpected explain call"
        return self.explain


def _ask(db_session, business_id, question, **kwargs):
    return answer_question(db_session, business_id=business_id, user_id="user-1", question=question, now=_NOW, **kwargs)


def test_how_to_question_is_routed_to_the_support_lane_and_grounded(db_session, business_id, monkeypatch):
    answer = (
        'Open Upload data and choose "Inventory / stock count", then select your file and select "Upload". '
        'Check the column matches, select "Confirm mapping", then select "Run import" under "Past uploads".'
    )
    provider = _FakeProvider(
        classify=_classify("product_help"),
        explain=_canned(json.dumps({"answerable": True, "answer": answer, "passage_ids": [_STOCK_PASSAGE]})),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "How do I upload my stock count?")

    assert result.intent == "product_help"
    assert result.grounded is True
    assert result.answer == answer
    assert result.help_articles == (("upload-stock-count", "Upload your stock count"),)
    assert result.help_answered is True
    assert result.handoff_available is True
    # Cost bound: exactly classify + explain.
    assert len(provider.calls) == 2
    explain_system = client.message_text(provider.calls[1][0])
    assert "ORLA Support Constitution" in explain_system
    assert "HELP PASSAGES:" in explain_system and _STOCK_PASSAGE in explain_system
    # No business data ever reaches the support prompt.
    assert "DATA:" not in explain_system
    lanes = sorted(r.lane for r in db_session.query(AIRequest).all())
    assert lanes == ["business_qa", "support"]


def test_business_data_question_keeps_the_deterministic_business_lane(db_session, business_id, monkeypatch):
    def _fake(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            return _classify("financial_performance")
        assert "ORLA Support Constitution" not in client.message_text(messages[0])
        return _canned("Your gross margin coverage is 0% right now — no cost data has been recorded yet.")

    monkeypatch.setattr(client, "chat_completion", _fake)

    result = _ask(db_session, business_id, "How's my revenue doing?")

    assert result.intent == "financial_performance"
    assert result.help_articles == ()
    assert result.handoff_available is False
    assert all(r.lane == "business_qa" for r in db_session.query(AIRequest).all())


def test_unanswerable_help_question_refuses_without_an_explain_call(db_session, business_id, monkeypatch):
    provider = _FakeProvider(classify=_classify("product_help"))
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "How do I connect ORLA to Shopify?")

    assert result.intent == "product_help"
    assert result.answer == support_lane.NO_ANSWER_MESSAGE
    assert result.help_answered is False
    assert result.handoff_available is True
    assert len(provider.calls) == 1  # classify only


def test_model_declining_becomes_a_handoff_offer(db_session, business_id, monkeypatch):
    provider = _FakeProvider(
        classify=_classify("product_help"),
        explain=_canned(json.dumps({"answerable": False, "answer": "", "passage_ids": []})),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "Can ORLA file my VAT return?")

    assert result.answer == support_lane.NO_ANSWER_MESSAGE
    assert result.help_answered is False
    assert result.handoff_available is True


def test_invented_steps_are_never_shown(db_session, business_id, monkeypatch):
    invented = 'Go to Settings, open "Integrations" and select "Sync stock now" to upload your stock count.'
    provider = _FakeProvider(
        classify=_classify("product_help"),
        explain=_canned(json.dumps({"answerable": True, "answer": invented, "passage_ids": [_STOCK_PASSAGE]})),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "How do I upload my stock count?")

    assert result.grounded is False
    assert result.answer == support_lane.UNVERIFIED_MESSAGE
    assert "Integrations" not in result.answer
    assert result.handoff_available is True


def test_citation_outside_the_retrieved_passages_is_rejected(db_session, business_id, monkeypatch):
    provider = _FakeProvider(
        classify=_classify("product_help"),
        explain=_canned(json.dumps({
            "answerable": True, "answer": 'Select "Generate reports now".', "passage_ids": ["reports#generate-reports-now"],
        })),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "How do I upload my stock count?")

    assert result.grounded is False
    assert result.answer == support_lane.UNVERIFIED_MESSAGE


def test_how_to_question_misclassified_out_of_scope_is_recovered(db_session, business_id, monkeypatch):
    answer = 'Open Reports and select "Generate reports now".'
    provider = _FakeProvider(
        classify=_classify("out_of_scope"),
        explain=_canned(json.dumps({"answerable": True, "answer": answer, "passage_ids": ["reports#generate-reports-now"]})),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "How do I generate reports now?")

    assert result.intent == "product_help"
    assert result.answer == answer
    assert result.help_articles == (("reports", "Weekly and monthly reports"),)


def test_off_topic_question_still_gets_the_plain_refusal(db_session, business_id, monkeypatch):
    provider = _FakeProvider(classify=_classify("out_of_scope"))
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "What's the capital of France?")

    assert result.intent == "out_of_scope"
    assert result.handoff_available is False
    assert len(provider.calls) == 1


def test_provider_down_still_points_to_the_right_article(db_session, business_id, monkeypatch):
    def _down(**kwargs):
        raise AIProviderError("down")

    monkeypatch.setattr(client, "chat_completion", _down)

    result = _ask(db_session, business_id, "How do I undo an import?")

    assert result.intent == "product_help"
    assert result.help_articles[0][0] == "undo-and-reimport"
    assert "Undo an import and re-import a file" in result.answer
    assert result.grounded is True


def test_provider_down_for_a_business_question_is_still_unavailable(db_session, business_id, monkeypatch):
    def _down(**kwargs):
        raise AIProviderError("down")

    monkeypatch.setattr(client, "chat_completion", _down)

    result = _ask(db_session, business_id, "What was my revenue last week?")

    assert result.intent == "provider_unavailable"


def test_compound_question_answers_the_help_part_without_extra_ai(db_session, business_id, monkeypatch):
    provider = _FakeProvider(
        classify=_canned(json.dumps({"intents": [
            {"intent": "metric_definition", "metric": "gross_margin"},
            {"intent": "product_help"},
        ]})),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "What is gross margin, and how do I undo an import?")

    assert result.intents == ("metric_definition", "product_help")
    assert "cost of goods sold" in result.answer
    assert ("undo-and-reimport", "Undo an import and re-import a file") in result.help_articles
    assert result.handoff_available is True
    assert len(provider.calls) == 1  # classify only — both parts resolved deterministically


def test_short_follow_up_reuses_the_previous_help_question_for_retrieval(db_session, business_id, monkeypatch):
    provider = _FakeProvider(
        classify=_classify("product_help"),
        explain=_canned(json.dumps({"answerable": False, "answer": "", "passage_ids": []})),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    _ask(
        db_session, business_id, "and how do I reverse it?",
        previous_question="How do I import my purchases file?", previous_answer="...", previous_intent="product_help",
    )

    explain_system = client.message_text(provider.calls[1][0])
    assert "undo-and-reimport#" in explain_system


def test_business_part_may_cite_a_number_from_the_help_part(db_session, business_id, monkeypatch):
    # ORLA-91 eval: the revenue part repeated the help summary's "7 days"
    # and the whole part was rejected as ungrounded.
    provider = _FakeProvider(
        classify=_canned(json.dumps({"intents": [
            {"intent": "financial_performance", "period": "default_recent"},
            {"intent": "product_help"},
        ]})),
        explain=_canned("⟦PART_1⟧\nRevenue was 0.00. Reports disappear after 7 days, as the help article says."),
    )
    monkeypatch.setattr(client, "chat_completion", provider)

    result = _ask(db_session, business_id, "What is my revenue, and how do I download a report?")

    assert result.grounded is True
    assert "7 days" in result.answer


def test_what_about_follow_up_keeps_the_action_and_switches_the_subject():
    # ORLA-91: "upload sales" outranked repairs, so the repairs steps never
    # reached the model.
    query = support_lane.retrieval_query(
        "And what about repairs?", previous_question="How do I upload my sales?", previous_intent="product_help"
    )
    assert query == "how do I upload repairs"
    assert support_lane.retrieve(query)[0].article_slug == "upload-repairs"
    # A follow-up that isn't "what about X" still uses the whole previous question.
    assert support_lane.retrieval_query(
        "and how do I reverse it?", previous_question="How do I import my purchases file?", previous_intent="product_help"
    ) == "How do I import my purchases file? and how do I reverse it?"
