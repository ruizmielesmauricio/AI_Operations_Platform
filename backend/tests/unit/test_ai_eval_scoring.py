"""The Ask ORLA eval's scorer (tests/ai_eval/scoring.py) — pure functions,
so a scoring bug can't silently inflate or deflate the reported pass rate."""

import json
from decimal import Decimal
from pathlib import Path

from tests.ai_eval.facts import Fact, known_fact_names
from tests.ai_eval.scoring import fact_present, leaked_tokens, score_turn

CONTEXT = {"parts": [{"context": {"revenue": {"current": "34166.77"}, "name": "Trailblazer MTB 29", "qty": 4}}]}


def _score(answer: str, *, expect=None, facts=(), intents=("financial_performance",), ai_calls=2, **kw):
    return score_turn(
        expect=expect or {"intent": "financial_performance"}, facts=list(facts), answer=answer, intents=intents,
        help_answered=kw.get("help_answered", False), handoff_available=kw.get("handoff_available", False),
        grounding_context=kw.get("context", CONTEXT), question=kw.get("question", "q"),
        previous_answer=None, ai_calls=ai_calls,
    )


def test_number_fact_matches_reformatted_money():
    assert fact_present("Revenue was €34,166.77 in October.", Fact(label="r", number=Decimal("34166.77")))


def test_number_fact_rejects_rounded_money():
    assert not fact_present("Revenue was about €34,167.", Fact(label="r", number=Decimal("34166.77")))


def test_attributed_fact_needs_name_and_number_in_same_line():
    fact = Fact(label="reorder", text="Trailblazer MTB 29", number=Decimal("4"))
    assert fact_present("1. Trailblazer MTB 29 — 4 units", fact)
    assert not fact_present("1. Trailblazer MTB 29 — 7 units\n2. CityRoll Hybrid 700c — 4 units", fact)


def test_zero_fact_can_be_stated_in_words():
    fact = Fact(label="r", number=Decimal("0.00"), zero_ok=True)
    assert fact_present("There were no sales recorded that day.", fact)
    assert not fact_present("Revenue was strong that day.", fact)


def test_alternative_figure_satisfies_fact():
    fact = Fact(label="prev", number=Decimal("35471.83"), alternatives=(Decimal("34086.98"),))
    assert fact_present("September came in at €34,086.98.", fact)


def test_leaks_detect_field_names_json_and_markers():
    assert leaked_tokens("- suggested_reorder_quantity: 49 units") == ["suggested_reorder_quantity"]
    assert "<json>" in leaked_tokens('{"revenue": 1}')
    assert "<part marker>" in leaked_tokens("⟦PART_1⟧ Revenue was fine.")
    assert leaked_tokens("Revenue was €34,166.77 from 1 Oct to 31 Oct.") == []


def test_passing_answer_passes_every_check():
    score = _score(
        "Revenue was €34,166.77 from 1 to 31 October.",
        facts=[Fact(label="r", number=Decimal("34166.77"))], context={**CONTEXT, "dates": ["1", "31"]},
    )
    assert score.passed, score.reasons


def test_unsupported_number_fails_grounding():
    score = _score("Revenue was €34,166.77, up 12% on last month.", facts=[Fact(label="r", number=Decimal("34166.77"))])
    assert not score.checks["grounded"]


def test_wrong_intent_fails():
    score = _score("Fine.", expect={"intent": "forecast"})
    assert not score.checks["intent"]


def test_multi_intent_requires_all_expected_intents():
    expect = {"intent": ["financial_performance", "forecast"], "multi": True}
    assert _score("ok", expect=expect, intents=("financial_performance", "forecast")).checks["intent"]
    assert not _score("ok", expect=expect, intents=("financial_performance",)).checks["intent"]


def test_refusal_behaviour():
    refusal = "I can help with questions about your revenue, retail and workshop performance — try one of those."
    assert _score(refusal, expect={"behaviour": "refuse"}).checks["behaviour"]
    assert not _score("Paris is the capital of France.", expect={"behaviour": "refuse"}).checks["behaviour"]
    assert not _score(refusal, expect={"behaviour": "answer"}).checks["behaviour"]


def test_forbidden_number_allowed_only_when_rejected():
    expect = {"forbid_numbers": ["99999"]}
    assert not _score("Yes, revenue was €99,999.", expect=expect, question="was it €99,999?").checks["forbidden"]
    assert _score(
        "Revenue was €34,166.77, not €99,999.", expect=expect, question="was it €99,999?"
    ).checks["forbidden"]


def test_repeated_sentence_fails():
    score = _score("You have 5 in stock.You have 5 in stock.", context={"n": 5})
    assert not score.checks["repeats"]


def test_ai_call_budget():
    assert not _score("ok", ai_calls=3).checks["ai_calls"]


def test_every_case_uses_known_facts_and_unique_ids():
    dataset = json.loads((Path(__file__).parents[1] / "ai_eval" / "cases.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in dataset["cases"]]
    assert len(ids) == len(set(ids))
    names = known_fact_names()
    for case in dataset["cases"]:
        for turn in case.get("turns", [case]):
            for spec in [*turn.get("facts", []), *turn.get("expect", {}).get("forbid_facts", [])]:
                assert spec["fact"] in names, (case["id"], spec)


def test_any_text_fact_needs_one_option():
    fact = Fact(label="latest", any_text=("INV-2026-1188", "Brake Pads Disc (pair)"))
    assert fact_present("Your latest delivery had 40 Brake Pads Disc (pair).", fact)
    assert not fact_present("Your latest delivery was some bikes.", fact)


def test_honest_no_data_phrasings_count_as_no_data():
    from tests.ai_eval.scoring import says_no_data

    assert says_no_data("I'm sorry, but the supplied data doesn't contain any information about rent payments.")
    assert says_no_data("Nothing weather-notable stands out for the week ahead right now.")
    assert not says_no_data("Revenue was strong last month.")
