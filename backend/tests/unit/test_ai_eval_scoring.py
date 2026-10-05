from decimal import Decimal

from app.ai.eval import scoring
from app.ai.eval.question_bank import QUESTIONS, Q
from app.ai.service import ALLOWED_INTENTS

_SAFE = "I can answer questions about ..."
_UNGROUNDED = "I couldn't confidently answer that"


def _q(**kw):
    base = dict(id="T-01", category="t", text="How did I do?", parts=({"intent": "financial_performance"},))
    base.update(kw)
    return Q(**base)


def _score(q, intents, answer, grounded=True, **kw):
    return scoring.score(
        q, actual_intents=tuple(intents), answer=answer, grounded=grounded,
        safe_fallbacks=(_SAFE,), ungrounded_fallback=_UNGROUNDED, ai_calls=2, **kw,
    )


def test_a_correctly_routed_grounded_answer_passes():
    assert _score(_q(), ["financial_performance"], "You sold €100.00 last week.").verdict == scoring.PASS


def test_wrong_routing_is_reported_with_both_sides():
    v = _score(_q(), ["retail_operations"], "Your best seller is X.")
    assert v.verdict == scoring.FAIL_ROUTING and "retail_operations" in v.reasons[0]


def test_an_accepted_alternative_routing_passes():
    q = _q(also_ok=(("findings_recommendations",),))
    assert _score(q, ["findings_recommendations"], "Nothing needs attention right now.").verdict == scoring.PASS


def test_declining_a_valid_question_is_its_own_failure():
    assert _score(_q(), ["out_of_scope"], _SAFE).verdict == scoring.FAIL_REFUSED


def test_an_answer_the_number_check_rejected_fails_as_ungrounded():
    assert _score(_q(), ["financial_performance"], _UNGROUNDED, grounded=False).verdict == scoring.FAIL_UNGROUNDED


def test_provider_outages_are_not_counted_as_quality_failures():
    assert _score(_q(), ["provider_unavailable"], "ORLA is temporarily unavailable").verdict == scoring.INFRA
    assert _score(_q(), ["usage_limit_reached"], "limit").verdict == scoring.INFRA


def test_internal_codes_or_markup_in_an_answer_fail():
    v = _score(_q(), ["financial_performance"], "intent was financial_performance: You sold €1.00 ```")
    assert v.verdict == scoring.FAIL_CONTENT


def test_a_refusal_must_decline_without_figures_or_leaks():
    q = _q(kind="refuse", parts=({"intent": "out_of_scope"},), must_not_contain=("DATA:",))
    assert _score(q, ["out_of_scope"], _SAFE).verdict == scoring.PASS
    assert _score(q, ["out_of_scope"], "Your profit is €1,000,000").verdict == scoring.FAIL_CONTENT
    assert _score(q, ["financial_performance"], "You made €5.00").verdict == scoring.FAIL_ANSWERED


def test_a_missing_expected_message_for_a_not_found_lookup_fails():
    q = _q(must_contain_any=("couldn't find",), parts=({"intent": "product_lookup"},))
    assert _score(q, ["product_lookup"], "It costs €9.00.").verdict == scoring.FAIL_CONTENT
    assert _score(q, ["product_lookup"], "I couldn't find a product by that name.").verdict == scoring.PASS


def test_the_answer_must_state_the_known_figure_when_one_is_given():
    q = _q()
    assert _score(q, ["financial_performance"], "You sold €4,758.24.", expected_figures=(Decimal("4758.24"),)).verdict == scoring.PASS
    assert _score(q, ["financial_performance"], "You sold €100.00.", expected_figures=(Decimal("4758.24"),)).verdict == scoring.FAIL_FIGURE


def test_the_question_bank_is_well_formed():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids))
    assert len(QUESTIONS) >= 200
    by_id = {q.id: q for q in QUESTIONS}
    for q in QUESTIONS:
        assert 1 <= len(q.parts) <= 3
        for part in q.parts:
            assert part["intent"] in ALLOWED_INTENTS, q.id
        for alt in q.also_ok:
            assert all(i in ALLOWED_INTENTS for i in alt), q.id
        if q.follow_up_to:
            assert q.follow_up_to in by_id and QUESTIONS.index(by_id[q.follow_up_to]) < QUESTIONS.index(q), q.id
        assert q.text.strip(), q.id
