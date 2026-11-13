"""Deterministic grounding check for the support lane (PR-5.7, ADR-028).

The business-data guardrail (app/ai/guardrail.py) checks numbers against
calculated data. A how-to answer has a different failure mode: an invented
step, button or page ("go to Settings > Integrations"). The prompt forbids
that, but a prompt is only a hint, so every support answer must pass these
pure checks before a user sees it:

1. The model must have declared the passages sufficient and cited at least
   one passage id, every one of which was actually supplied.
2. No links or URLs — article links are attached by code, never by the
   model.
3. Every number in the answer appears in the cited passages (or in the
   question itself).
4. Every quoted UI label ("Run import", “Upload data”) appears verbatim in
   the cited passages — the main defence against invented buttons.
5. At least ``MIN_SUPPORT_RATIO`` of the answer's meaningful words appear in
   the cited passages or the question — an answer that drifts into content
   the passages do not contain fails, rather than being shown.

Any failure means the answer is discarded and the user is offered the
human handoff instead. No I/O, no network: fully unit-testable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.ai.guardrail import extract_numeric_claims
from app.support.knowledge_base import tokenize

MAX_ANSWER_CHARS = 1500
# Calibrated so a faithful paraphrase passes (the model re-words, adds
# connectives like "then"/"next") while an answer built from content the
# passages do not contain fails.
MIN_SUPPORT_RATIO = 0.75
_URL_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)
_QUOTED_PATTERN = re.compile(r"[\"“”]([^\"“”]{2,80})[\"“”]")
# Words the model legitimately adds when turning reference text into an
# answer, which never carry a factual claim of their own.
_CONNECTIVE_WORDS = frozenset(
    tokenize(
        "first second third next then finally step steps once after afterwards also simply just sure yes "
        "following follow page option button select click choose open go see article help answer question "
        "need needs able way ways like make sure note"
    )
)


@dataclass(frozen=True)
class SupportModelOutput:
    answerable: bool
    answer: str
    passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class SupportGuardResult:
    grounded: bool
    reasons: list[str] = field(default_factory=list)
    support_ratio: float = 0.0


def parse_support_output(content: str | None) -> SupportModelOutput | None:
    """The explain call is asked for a JSON object
    {"answerable": bool, "answer": str, "passage_ids": [str]}. Anything else
    (no content, prose, wrong types) returns None — treated exactly like an
    unanswerable question, never shown."""
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    answerable = data.get("answerable")
    answer = data.get("answer")
    passage_ids = data.get("passage_ids")
    if not isinstance(answerable, bool) or not isinstance(answer, str):
        return None
    if not isinstance(passage_ids, list) or not all(isinstance(p, str) for p in passage_ids):
        return None
    return SupportModelOutput(answerable=answerable, answer=answer.strip(), passage_ids=tuple(passage_ids))


def _normalise(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").replace("’", "'").split())


def _number_tokens(text: str) -> set[str]:
    return {claim.replace(",", "").rstrip("%").rstrip(".") for claim in extract_numeric_claims(text)}


def verify_support_answer(
    output: SupportModelOutput,
    *,
    passages_by_id: dict[str, str],
    question: str,
) -> SupportGuardResult:
    reasons: list[str] = []
    if not output.answerable:
        return SupportGuardResult(False, ["model_declared_unanswerable"])
    if not output.answer:
        return SupportGuardResult(False, ["empty_answer"])
    if len(output.answer) > MAX_ANSWER_CHARS:
        reasons.append("answer_too_long")
    cited = [pid for pid in output.passage_ids if pid in passages_by_id]
    if not output.passage_ids or len(cited) != len(output.passage_ids):
        reasons.append("unknown_or_missing_citation")
    if not cited:
        return SupportGuardResult(False, reasons or ["no_citation"])

    source = "\n".join(passages_by_id[pid] for pid in cited)
    source_norm = _normalise(source)

    if _URL_PATTERN.search(output.answer):
        reasons.append("contains_link")

    allowed_numbers = _number_tokens(source) | _number_tokens(question)
    for number in _number_tokens(output.answer):
        if number and number not in allowed_numbers:
            reasons.append(f"unsupported_number:{number}")

    for label in _QUOTED_PATTERN.findall(output.answer):
        if _normalise(label).strip(" .,:;!?") not in source_norm:
            reasons.append(f"unsupported_label:{label}")

    source_tokens = set(tokenize(source)) | set(tokenize(question))
    answer_tokens = [t for t in tokenize(output.answer) if t not in _CONNECTIVE_WORDS and not t.isdigit()]
    if answer_tokens:
        supported = sum(1 for t in answer_tokens if t in source_tokens)
        ratio = supported / len(answer_tokens)
    else:
        ratio = 0.0
        reasons.append("no_content")
    if ratio < MIN_SUPPORT_RATIO:
        reasons.append(f"low_support:{ratio:.2f}")

    return SupportGuardResult(grounded=not reasons, reasons=reasons, support_ratio=round(ratio, 3))
