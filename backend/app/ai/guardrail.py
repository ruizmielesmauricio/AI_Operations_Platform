"""Deterministic enforcement of PR-5.3 — "reject or flag any AI numeric
claim not present in structured input." The AI's system prompt (see
app/ai/service.py) *asks* it to stick to the given data, but a prompt is
a hint, not a guarantee; this module is what actually holds regardless
of what the model does. Every function here is pure — no I/O, no
network — so it's fully unit-testable and matches this codebase's
"Business Logic First" charter even though it lives under app/ai/ (the
guardrail itself is not AI, it's deterministic Python guarding AI).
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

_NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*\.?\d*%?")
_UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@dataclass(frozen=True)
class GuardrailResult:
    grounded: bool
    # The exact substrings from the answer that couldn't be traced back
    # to the structured context — empty when grounded is True. Kept for
    # logging (app/ai/service.py logs these on rejection), never shown
    # to the end user as-is.
    unsupported_claims: list[str] = field(default_factory=list)


def extract_numeric_claims(text: str) -> list[str]:
    """Every numeric-looking substring in an AI answer, exactly as
    written (kept as raw strings, not yet parsed, so a caller can log
    precisely what was flagged)."""
    return _NUMBER_PATTERN.findall(text)


def _parse_claim(raw: str) -> Decimal | None:
    cleaned = raw.replace(",", "").rstrip("%")
    if not cleaned or cleaned in ("-", "+", "."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _add(values: set[Decimal], value: Decimal) -> None:
    values.add(value)
    if value < 0:
        values.add(abs(value))


def flatten_numeric_values(context: Any) -> set[Decimal]:
    """Every number reachable anywhere inside a structured context
    (recursively — dicts, lists, nested values). Handles both a native
    int/float and a Decimal-serialized JSON string (this codebase
    serializes Decimal fields to strings — see app/schemas/analytics.py
    and the frontend's types/index.ts note — so a money/percentage
    figure normally arrives here as a string like "39.90", not a float).
    Booleans are explicitly excluded (Python's bool is an int subclass —
    True/False must never be treated as the number 1/0).

    Known, stated limitation: `retail_operations.sell_through_rate` is
    stored as a raw 0-1 fraction (e.g. "0.62"), not already multiplied
    into a percentage — the same field the frontend's formatRate()
    multiplies by 100 only at display time. An AI answer that phrases
    this as "62%" will not find "62" in the flattened context and gets
    rejected. The system prompt (app/ai/service.py) is told to state
    this field as given rather than convert it, to avoid tripping this;
    a general unit-aware conversion isn't built here.

    A negative number's absolute value is included alongside the signed
    value — live-verified this is necessary, not theoretical: a real
    model naturally phrased `revenue.change_pct = "-35.7"` as "revenue
    was down 35.7%" (no minus sign in the prose), exactly how this
    codebase's own app/analytics/report_narrative.py already phrases a
    decline (`abs(revenue.change_pct)` + the word "decreased"). Without
    this, a perfectly grounded answer about a decline would always fail.

    Numbers embedded inside a mixed alphanumeric string (a product name
    like "CityRoll MTB 200") are also pulled out and allowed — another
    live-verified real bug: a product name containing a model number is
    legitimate context the AI can repeat verbatim, but the original
    version of this function only recognised a value as numeric if the
    *entire* string parsed as one, so "200" inside a name was invisible
    to it and any answer that named the product got wrongly rejected.
    UUID-shaped strings (product/business ids) are exempted from this —
    their digit runs are structurally meaningless and would only dilute
    the guardrail's protection against a genuinely invented number.
    """
    values: set[Decimal] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            _add(values, Decimal(str(node)))
        elif isinstance(node, str):
            parsed = _parse_claim(node)
            if parsed is not None:
                _add(values, parsed)
            elif not _UUID_PATTERN.match(node):
                for raw in extract_numeric_claims(node):
                    embedded = _parse_claim(raw)
                    if embedded is not None:
                        _add(values, embedded)
        elif isinstance(node, dict):
            for value in node.values():
                _walk(value)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                _walk(item)

    _walk(context)
    return values


def validate_grounded(answer_text: str, context: Any) -> GuardrailResult:
    """PR-5.3's actual enforcement: every numeric claim in `answer_text`
    must equal some number found anywhere in `context` (Decimal equality
    ignores trailing-zero formatting differences, e.g. Decimal("39.9")
    == Decimal("39.90") — but not rounding: "€11,908" will not match a
    true 11907.76, by design. Fails closed on any ambiguity rather than
    silently accepting a rounded/reworded figure — better to occasionally
    reject a legitimate answer than let an invented number through). A
    claim that fails to parse as a number is skipped, not flagged (it
    wasn't a numeric claim at all — e.g. a list marker or a stray word
    fragment the regex still matched)."""
    allowed = flatten_numeric_values(context)
    unsupported: list[str] = []

    for raw_claim in extract_numeric_claims(answer_text):
        parsed = _parse_claim(raw_claim)
        if parsed is None:
            continue
        if parsed not in allowed:
            unsupported.append(raw_claim)

    return GuardrailResult(grounded=len(unsupported) == 0, unsupported_claims=unsupported)
