"""The conversational agent's product/support lane (PR-5.7, ADR-020,
ADR-028): how-to questions about the ORLA app are answered only from the
approved help knowledge base (app/support/content/).

Pipeline, once the classifier (app/ai/service.py) has picked the
"product_help" lane:

    retrieve (deterministic, app/support/knowledge_base.py)
      -> not confident?  refuse + offer handoff        (no further AI call)
      -> explain from the retrieved passages only       (1 AI call, JSON)
      -> verify (deterministic, app/ai/support_guard.py)
      -> fails?  refuse + offer handoff
      -> answer + links to the cited articles

Cost stays bounded at the same two calls per question as the business-data
lane (classify + explain), and an unanswerable question costs only the
classify call. Article links are built from the cited passage ids by code —
never from text the model produced.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.ai import client
from app.ai.exceptions import AIProviderError
from app.ai.support_guard import parse_support_output, verify_support_answer
from app.repositories.ai_request import AIRequestRepository
from app.support.knowledge_base import RetrievedPassage, get_knowledge_base, is_confident
from app.settings.config import get_settings

logger = logging.getLogger(__name__)

LANE = "support"
INTENT = "product_help"
_PROVIDER = "openrouter"
# Passages handed to the model are capped so a long article cannot blow up
# the prompt (and the per-question cost).
_MAX_PASSAGES = 4
_MAX_PASSAGE_CHARS = 1800
# A related-article suggestion is only shown under a refusal when the best
# (non-confident) match is at least this strong — below it the suggestion
# would be noise.
_RELATED_ARTICLE_MIN_SCORE = 3.0
_MAX_RELATED_ARTICLES = 2

NO_ANSWER_MESSAGE = (
    "I couldn't find the answer to that in ORLA's help articles, so I won't guess. "
    'Select "Contact support" to send your question to the ORLA team — they will follow up with you.'
)
UNVERIFIED_MESSAGE = (
    "I couldn't give you an answer I'm sure is correct from ORLA's help articles, so I won't guess. "
    'Select "Contact support" to ask the ORLA team — they will follow up with you.'
)

_SYSTEM_PROMPT = (Path(__file__).parent / "orla_support_constitution.md").read_text(encoding="utf-8")

# Question shapes that are almost always about using the app rather than
# about the business's own numbers. Used only as defence in depth (to
# recover a how-to question the classifier wrongly called out_of_scope, or
# to answer one deterministically while the AI provider is down) — and
# only ever together with a confident retrieval match.
_HOW_TO_PATTERN = re.compile(
    r"^\s*(?:"
    r"how (?:do|can|should|would|could) (?:i|we|you|my|our)\b|how to\b|"
    r"where (?:do|can|is|are|should) |"
    r"why (?:did|does|do|is|are|can't|cannot|won't|isn't|doesn't|has|have)\b|"
    r"can (?:i|we|my|our)\b|is it possible|what happens (?:if|when)|"
    r"i (?:can't|cannot|can not|don't know how)\b|"
    r"(?:i need|i want|i'd like) (?:to|help)\b|help\b"
    r")",
    re.IGNORECASE,
)
_SUPPORT_WORDS_PATTERN = re.compile(
    r"\b(?:contact support|talk to (?:a|someone|a person|a human)|speak to (?:a|someone)|human|"
    r"customer service|report a (?:bug|problem))\b",
    re.IGNORECASE,
)


def looks_like_how_to_question(question: str) -> bool:
    return bool(_HOW_TO_PATTERN.search(question) or _SUPPORT_WORDS_PATTERN.search(question))


_CLAUSE_SPLIT_PATTERN = re.compile(r"[?.!;]+|,?\s+\b(?:and|also|plus|then)\b\s+|,\s+", re.IGNORECASE)


def how_to_clause(question: str) -> str:
    """For a compound question ("what's my margin, and how do I undo an
    import?"), the clause(s) that are actually the how-to part — so help
    retrieval isn't pulled towards the business-data half. Falls back to
    the whole question when no clause stands out."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT_PATTERN.split(question) if c and c.strip()]
    how_to = [c for c in clauses if looks_like_how_to_question(c)]
    return " ".join(how_to) if how_to and len(how_to) < len(clauses) else question


@dataclass(frozen=True)
class SupportAnswer:
    answer: str
    # True when the answer is either a verified help answer or a safe,
    # deterministic refusal; False when a model answer was rejected by the
    # verifier (mirrors the business lane's ungrounded-fallback convention).
    grounded: bool
    # (slug, title) of the help articles the answer links to, best first.
    articles: tuple[tuple[str, str], ...]
    # Whether the answer came from the help content (False = refusal).
    answered: bool
    # Machine-readable reason for logs/tests: answered | no_match |
    # model_declined | unverified | provider_unavailable.
    outcome: str


def retrieval_query(question: str, *, previous_question: str | None, previous_intent: str | None) -> str:
    """A short follow-up to a help answer ("and how do I undo it?") rarely
    names its subject, so the previous help question is added to the
    retrieval query — only when the previous turn was itself a help answer,
    so a business-data exchange never leaks into help retrieval."""
    if previous_intent == INTENT and previous_question and len(question.split()) <= 8:
        swapped = _same_action_new_subject(question, previous_question)
        return swapped if swapped is not None else f"{previous_question} {question}"
    return question


# "And what about repairs?" after "How do I upload my sales?" asks the same
# action about a new subject. Found by the ORLA-91 model comparison: adding
# the whole previous question let its subject ("upload sales", a key
# phrase) outrank the new one, so the repairs steps never reached the model
# and it rightly refused.
_NEW_SUBJECT_PATTERN = re.compile(
    r"^\s*(?:and\s+)?(?:what|how)\s+about\s+(?P<subject>.+?)\s*[?.!]*\s*$|^\s*(?:and\s+)?(?:same\s+)?for\s+(?P<subject2>.+?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
_ACTION_WORDS = frozenset(
    {
        "upload", "import", "export", "undo", "reverse", "delete", "remove", "add", "invite", "change", "edit",
        "update", "download", "generate", "set", "connect", "cancel", "map", "reimport", "re-import",
    }
)


def _same_action_new_subject(question: str, previous_question: str) -> str | None:
    match = _NEW_SUBJECT_PATTERN.match(question)
    if match is None:
        return None
    subject = match.group("subject") or match.group("subject2")
    actions = [w for w in re.findall(r"[a-z-]+", previous_question.lower()) if w in _ACTION_WORDS]
    if not subject or not actions:
        return None
    return f"how do I {' '.join(dict.fromkeys(actions))} {subject}"


def retrieve(query: str) -> list[RetrievedPassage]:
    return get_knowledge_base().retrieve(query, limit=_MAX_PASSAGES)


def confident_match(question: str) -> bool:
    return is_confident(retrieve(question))


def _articles_from_passages(passages: list[RetrievedPassage], limit: int) -> tuple[tuple[str, str], ...]:
    seen: dict[str, str] = {}
    for p in passages:
        seen.setdefault(p.article_slug, p.article_title)
        if len(seen) >= limit:
            break
    return tuple(seen.items())


def _related_articles(passages: list[RetrievedPassage]) -> tuple[tuple[str, str], ...]:
    # Live-found: "how do I connect ORLA to my Shopify store?" suggested
    # "Sign up and log in" because "connect" matched one sentence there.
    # A suggestion must match more than half of the question's words.
    if not passages or passages[0].score < _RELATED_ARTICLE_MIN_SCORE or passages[0].coverage <= 0.5:
        return ()
    return _articles_from_passages(passages, _MAX_RELATED_ARTICLES)


def deterministic_pointer(question: str) -> SupportAnswer:
    """A zero-AI answer: the best-matching article's own summary and a link.
    Used for the help part of a multi-part question (so the shared explain
    call stays business-data only) and while the AI provider is down. Every
    word comes from the article's reviewed front-matter."""
    passages = retrieve(question)
    if not is_confident(passages):
        return SupportAnswer(NO_ANSWER_MESSAGE, True, _related_articles(passages), False, "no_match")
    kb = get_knowledge_base()
    article = kb.get(passages[0].article_slug)
    assert article is not None  # retrieved passages always belong to a loaded article
    text = f"The help article “{article.title}” covers this: {article.summary}"
    return SupportAnswer(text, True, ((article.slug, article.title),), True, "answered")


def answer_from_help(
    request_repo: AIRequestRepository,
    *,
    business_id: uuid.UUID,
    user_id: str,
    question: str,
    previous_question: str | None = None,
    previous_answer: str | None = None,
    previous_intent: str | None = None,
) -> SupportAnswer:
    passages = retrieve(retrieval_query(question, previous_question=previous_question, previous_intent=previous_intent))
    if not is_confident(passages):
        # Nothing in the help content is a strong match: refuse without
        # spending an explain call, and offer the human handoff.
        return SupportAnswer(NO_ANSWER_MESSAGE, True, _related_articles(passages), False, "no_match")

    passages_by_id = {p.passage_id: p.text[:_MAX_PASSAGE_CHARS] for p in passages}
    payload = [
        {"id": p.passage_id, "article": p.article_title, "section": p.heading, "text": passages_by_id[p.passage_id]}
        for p in passages
    ]
    messages = [{"role": "system", "content": f"{_SYSTEM_PROMPT}\n\nHELP PASSAGES:\n{json.dumps(payload)}"}]
    if previous_intent == INTENT and previous_question and previous_answer:
        messages.append({"role": "user", "content": previous_question})
        messages.append({"role": "assistant", "content": previous_answer})
    messages.append({"role": "user", "content": question})

    try:
        # Same reasoning-token headroom rationale as the business lane's
        # explain call (app/ai/service.py::_generate_answer): the default
        # model spends hidden reasoning tokens before the visible JSON.
        # Live-measured on the dev stack (13/11/2026): a five-step answer
        # used ~480 reasoning + ~70 visible tokens; 1400 leaves room for a
        # longer answer without silently truncating to no content.
        response = client.chat_completion(
            messages=messages, response_format={"type": "json_object"}, max_tokens=get_settings().ai_support_max_tokens,
            temperature=0.0,
        )
    except AIProviderError as exc:
        logger.warning("AI support explain call failed business=%s error=%s", business_id, exc)
        _log(request_repo, business_id=business_id, user_id=user_id, model="unknown", success=False)
        pointer = deterministic_pointer(question)
        return SupportAnswer(pointer.answer, True, pointer.articles, pointer.answered, "provider_unavailable")

    content, tokens_in, tokens_out, model, cost = _extract(response)
    _log(
        request_repo, business_id=business_id, user_id=user_id, model=model,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_eur=cost, success=content is not None,
    )

    output = parse_support_output(content)
    if output is None or not output.answerable:
        # Logged so a refusal can be told apart from a provider/format
        # problem (e.g. the reasoning model spending its whole token budget
        # before emitting JSON, which returns no content at all).
        logger.warning(
            "Support explain declined business=%s parsed=%s tokens_out=%s content=%r",
            business_id, output is not None, tokens_out, (content or "")[:300],
        )
        return SupportAnswer(NO_ANSWER_MESSAGE, True, _related_articles(passages), False, "model_declined")

    result = verify_support_answer(output, passages_by_id=passages_by_id, question=question)
    if not result.grounded:
        logger.warning(
            "Ungrounded support answer rejected business=%s reasons=%s", business_id, result.reasons
        )
        return SupportAnswer(UNVERIFIED_MESSAGE, False, _related_articles(passages), False, "unverified")

    cited = [p for pid in output.passage_ids for p in passages if p.passage_id == pid]
    return SupportAnswer(output.answer, True, _articles_from_passages(cited, _MAX_RELATED_ARTICLES), True, "answered")


def _extract(response: dict) -> tuple[str | None, int, int, str, Decimal]:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = None
    usage = response.get("usage") or {}
    raw_cost = usage.get("cost")
    return (
        content,
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        response.get("model") or "unknown",
        Decimal(str(raw_cost)) if raw_cost is not None else Decimal("0"),
    )


def _log(
    request_repo: AIRequestRepository,
    *,
    business_id: uuid.UUID,
    user_id: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_eur: Decimal = Decimal("0"),
    success: bool = True,
) -> None:
    request_repo.create(
        business_id=business_id, user_id=user_id, lane=LANE, provider=_PROVIDER, model=model,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_eur=cost_eur, success=success,
    )
