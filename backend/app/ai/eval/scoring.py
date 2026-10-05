"""Pure scoring rules: given a question and what ORLA returned, decide
PASS or say exactly why not. No I/O, so it is unit-tested directly
(tests/unit/test_ai_eval_scoring.py).
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.ai.eval.question_bank import Q
from app.ai.guardrail import extract_numeric_claims

PASS = "PASS"
SKIPPED = "SKIPPED"
INFRA = "INFRA"  # the AI provider/limits, not answer quality
FAIL_ROUTING = "FAIL_ROUTING"          # picked the wrong kind of data
FAIL_REFUSED = "FAIL_REFUSED"          # declined a question it should answer
FAIL_ANSWERED = "FAIL_ANSWERED"        # answered one it should decline
FAIL_UNGROUNDED = "FAIL_UNGROUNDED"    # an answer the number-check rejected
FAIL_CONTENT = "FAIL_CONTENT"          # leaked markup/internals, or missing the expected message
FAIL_FIGURE = "FAIL_FIGURE"            # didn't state the figure it should have
FAIL_ERROR = "FAIL_ERROR"              # the pipeline raised

FAIL_VERDICTS = (FAIL_ROUTING, FAIL_REFUSED, FAIL_ANSWERED, FAIL_UNGROUNDED, FAIL_CONTENT, FAIL_FIGURE, FAIL_ERROR)

# Things an owner must never see in an answer.
_LEAK_PATTERNS = (
    "⟦", "```", '"intent"', "{'intent'", "provider_unavailable", "out_of_scope", "financial_performance",
    "retail_operations", "as an ai language model", "traceback", "nan%", "€nan", "undefined", "None%", "€None",
    "DATA:", "constitution",
)

_INFRA_INTENTS = ("provider_unavailable", "usage_limit_reached")


@dataclass(frozen=True)
class Verdict:
    verdict: str
    reasons: tuple[str, ...] = ()


def _decimals(text: str) -> list[Decimal]:
    out = []
    for raw in extract_numeric_claims(text):
        try:
            out.append(Decimal(raw.replace(",", "").rstrip("%")))
        except InvalidOperation:
            continue
    return out


def states_figure(answer: str, expected: Decimal) -> bool:
    """True when the answer states `expected` exactly (the number check
    already rejects rounded figures, so exact equality is the right bar)."""
    return any(d == expected or d == abs(expected) for d in _decimals(answer))


def score(
    q: Q,
    *,
    actual_intents: tuple[str, ...],
    answer: str,
    grounded: bool,
    safe_fallbacks: tuple[str, ...],
    ungrounded_fallback: str,
    ai_calls: int,
    expected_figures: tuple[Decimal, ...] = (),
    expected_parts: tuple[dict, ...] | None = None,
) -> Verdict:
    if actual_intents and actual_intents[0] in _INFRA_INTENTS:
        return Verdict(INFRA, (actual_intents[0],))

    lowered = answer.lower()
    leaks = [p for p in _LEAK_PATTERNS if p.lower() in lowered]
    # Refusals may legitimately not leak either; same rule everywhere.
    forbidden = [t for t in q.must_not_contain if t.lower() in lowered]

    if q.kind == "refuse":
        reasons: list[str] = []
        if actual_intents and actual_intents[0] not in ("out_of_scope",) and tuple(actual_intents) not in q.also_ok:
            # It tried to answer. That is only acceptable if it stayed grounded.
            return Verdict(FAIL_ANSWERED, (f"answered as {','.join(actual_intents)}",))
        if forbidden:
            reasons.append("repeated a forbidden phrase: " + ", ".join(forbidden))
        if leaks:
            reasons.append("leaked internals: " + ", ".join(leaks))
        if re.search(r"\d", answer) and actual_intents == ("out_of_scope",):
            reasons.append("a refusal should contain no figures")
        return Verdict(FAIL_CONTENT if reasons else PASS, tuple(reasons))

    acceptable = {q.intents, *q.also_ok}
    if tuple(actual_intents) not in acceptable:
        if actual_intents == ("out_of_scope",):
            return Verdict(FAIL_REFUSED, ("declined a question it should answer",))
        return Verdict(FAIL_ROUTING, (f"expected {'+'.join(q.intents)}, got {'+'.join(actual_intents)}",))

    if answer in safe_fallbacks and "out_of_scope" not in q.intents:
        return Verdict(FAIL_REFUSED, ("gave the generic 'can't help' reply",))
    if not grounded or answer == ungrounded_fallback or ungrounded_fallback in answer:
        return Verdict(FAIL_UNGROUNDED, ("the answer failed the number check",))

    reasons = []
    if len(answer.strip()) < 10:
        reasons.append("answer is empty or too short")
    if leaks:
        reasons.append("leaked internals: " + ", ".join(leaks))
    if forbidden:
        reasons.append("repeated a forbidden phrase: " + ", ".join(forbidden))
    if q.must_contain_any and not any(t.lower() in lowered for t in q.must_contain_any):
        reasons.append("missing the expected message (" + " / ".join(q.must_contain_any[:3]) + ")")
    if reasons:
        return Verdict(FAIL_CONTENT, tuple(reasons))

    missing = [str(f) for f in expected_figures if not states_figure(answer, f)]
    if expected_figures and len(missing) == len(expected_figures):
        return Verdict(FAIL_FIGURE, ("did not state the expected figure: " + " or ".join(missing),))

    return Verdict(PASS)
