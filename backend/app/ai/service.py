"""Orchestrates PR-5.6's business-data Q&A lane: classify -> fetch ->
explain -> guard, per ADR-020 ("route every conversational-agent
question through an intent classifier that selects one of a fixed,
approved set of deterministic query functions... before any AI
generation occurs — no free-form calculation, retrieval, or invention
outside these approved sources"). No calculation logic of its own —
every number in a `context` dict passed to the model came from an
existing C9-C13/D17-18 application function before this module ever
saw it.
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.ai import client
from app.ai.exceptions import AIProviderError
from app.ai.glossary import ALLOWED_METRIC_KEYS, get_definition, match_definition_question
from app.ai.guardrail import validate_grounded
from app.analytics.period import compute_report_period
from app.application.business_group import (
    MixedTimezoneGroup,
    NotGroupMember,
    get_financial_performance_for_group,
    get_findings_for_group,
    get_forecast_for_group,
    get_retail_operations_for_group,
    get_workshop_performance_for_group,
    resolve_authorized_group,
)
from app.application.category_breakdown import get_category_breakdown
from app.application.financial_performance import get_financial_performance
from app.application.findings import get_findings
from app.application.forecast import get_forecast
from app.application.lookups import find_products, find_purchases, find_repairs
from app.application.retail_operations import get_retail_operations
from app.application.workshop_performance import get_workshop_performance
from app.models.business import Business
from app.repositories.ai_request import AIRequestRepository
from app.repositories.business import list_businesses_for_user
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.report import ReportRepository
from app.schemas.analytics import (
    CategoryBreakdownOut,
    FinancialPerformanceOut,
    FindingsOut,
    ForecastOut,
    RetailOperationsOut,
    WorkshopPerformanceOut,
)
from app.settings.config import get_settings

logger = logging.getLogger(__name__)

# The fixed, approved set ADR-020 requires — every entry maps straight
# to an existing deterministic application function (or the static
# glossary). A classifier response outside this set is never trusted,
# regardless of what the model returns. product_lookup/purchase_lookup/
# repair_lookup added after live testing showed a real ceiling: ORLA
# could only answer aggregate questions over 3 fixed periods, not
# "when did X happen"/"how much stock of Y"/"what did I order under
# PO-123"/"how much did repair Z cost" — real questions a business
# owner asks, and the underlying data (InventoryMovement.
# purchase_reference/event_date, ProductionEvent.repair_reference) was
# already there, just never made queryable per-record. category_breakdown
# added after live testing showed another real gap: "what's my biggest
# cost/expense" questions had no intent to land in at all (classified
# out_of_scope, or landed on financial_performance — which has no
# per-category cost breakdown to actually ground an answer in) — reuses
# app/application/category_breakdown.py, already built for the dashboard
# and reports.
ALLOWED_INTENTS = (
    "financial_performance",
    "retail_operations",
    "workshop_performance",
    "forecast",
    "findings_recommendations",
    "latest_report",
    "metric_definition",
    "product_lookup",
    "purchase_lookup",
    "purchase_history",
    "repair_lookup",
    "category_breakdown",
    "out_of_scope",
)
# explicit_date added alongside the lookup intents — a question naming a
# specific date/range ("revenue on the 24th of June") previously had no
# period value that could represent it at all.
ALLOWED_PERIODS = ("default_recent", "last_completed_week", "last_completed_month", "explicit_date")
_MAX_SEARCH_TERM_LENGTH = 200
# Multi-intent cap — a compound question ("what's my revenue and what
# should I reorder") gets split into at most this many sub-questions, in
# the same single classify call (see _classify_intent) rather than a
# separate planner call, to keep AI cost bounded at exactly 2 calls
# (classify + explain) per question regardless of how many things were
# asked.
_MAX_SUBINTENTS = 3
_MAX_EXPLICIT_DATE_YEARS_BACK = 10
_MAX_EXPLICIT_DATE_YEARS_FORWARD = 1
# Same bounds the /forecast API route already enforces (Query(7, ge=1,
# le=90) in app/api/analytics.py) — kept in sync deliberately, not
# imported, since this module doesn't otherwise depend on the API layer.
_MIN_HORIZON_DAYS = 1
_MAX_HORIZON_DAYS = 90
_DEFAULT_HORIZON_DAYS = 7
# Last-exchange-only conversation memory (see answer_question's own
# docstring): how much of the previous answer's text is given to the
# *classify* call specifically. Classify only needs enough to tell what
# topic/period a follow-up is referring to, not the full text — kept
# short to control the reasoning-token-budget risk this module already
# hit once from a growing classify prompt (see _classify_intent's own
# max_tokens comment). The *explain* call gets the full previous_answer,
# uncapped here — it has a bigger budget and benefits from full fidelity.
_CLASSIFY_PREVIOUS_ANSWER_MAX_CHARS = 500

_LANE = "business_qa"
_PROVIDER = "openrouter"

_SAFE_FALLBACK = (
    "I can help with questions about your revenue, retail and workshop performance, forecast, "
    "recommendations, or your latest weekly/monthly report — try asking about one of those."
)
_UNAVAILABLE_MESSAGE = "ORLA is temporarily unavailable — your dashboard and reports are unaffected. Try again shortly."
_USAGE_LIMIT_MESSAGE = "This business has reached its question limit with ORLA for today. Try again tomorrow."
_UNGROUNDED_FALLBACK = "I couldn't confidently answer that from your actual data — try rephrasing, or check the dashboard directly."


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    # The first (or only) sub-question's intent — kept singular so every
    # existing caller (previous_intent's own _CONTINUABLE_INTENTS checks,
    # the API layer, the frontend) keeps working unchanged. `intents`
    # below carries the full list for a multi-intent answer.
    intent: str
    grounded: bool
    # A fixed, small set of app pages the answer references — always
    # {"dashboard", "reports"} or empty, never arbitrary text/URLs from
    # the model. The frontend renders these as real, safe <a> elements
    # itself (app/chat/page.tsx) rather than ever treating any part of
    # `answer` (which may include model-generated text) as HTML.
    links: tuple[str, ...] = ()
    # Every sub-question's intent, in question order — length 1 for an
    # ordinary single-intent question (matching `intent` above), longer
    # for a compound one. Echoed back by the frontend as the next
    # request's previous_intents, so a follow-up after a multi-part
    # answer can still recover via _CONTINUABLE_INTENTS against any part
    # of it, not just the first.
    intents: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassifyResult:
    """What the classify call decided, already server-side validated —
    every field is either one of this module's fixed allowed values or
    None/a bounded plain value; nothing here is trusted as-is past this
    point (see _parse_intent_json). Replaced a bare 3-tuple once
    start_date/end_date/search_term made the return shape big enough
    that positional unpacking was no longer readable."""

    intent: str
    period: str = "default_recent"
    start_date: date | None = None
    end_date: date | None = None
    metric: str | None = None
    search_term: str | None = None
    # Only meaningful for "forecast" — how many days ahead the question
    # actually asked about ("next two weeks" -> 14). None means "use the
    # default 7". Added after a live fire-test found a real bug: a
    # question about "the next two weeks" was answered against the
    # default 7-day forecast, so the model's own correct "14 days"
    # phrasing had no matching horizon in the fetched context and the
    # guardrail (rightly) rejected it — the fix is giving the classify
    # step a way to ask for the actual horizon the question named, not
    # loosening the guardrail.
    horizon_days: int | None = None


@dataclass(frozen=True)
class _Part:
    """One sub-question's worth of work inside a (possibly multi-intent)
    answer — see answer_question's own docstring for how these compose.
    `resolved_answer` set means this part is already fully and
    deterministically answered (a metric definition, a lookup's 0/many-
    match message, a "no data for this" note, or an unresolved
    out_of_scope refusal) — zero further AI cost for it, and the shared
    explain call never sees it. Unset means `context` is what the shared
    explain call needs to answer it, same shape as every intent's context
    always was."""

    intent: str
    resolved_answer: str | None = None
    context: dict | None = None
    # Only ever set for a "forecast" part — see _build_part and
    # _assemble_final_answer's own comments (mirrors the original
    # single-question _all_products_for_priority_list handling).
    all_products_for_priority_list: list | None = None


def answer_question(
    db: Session,
    *,
    business_id: uuid.UUID,
    user_id: str,
    question: str,
    now: datetime | None = None,
    all_branches: bool = False,
    previous_question: str | None = None,
    previous_answer: str | None = None,
    previous_intent: str | None = None,
    previous_intents: list[str] | None = None,
) -> AnswerResult:
    """`previous_question`/`previous_answer` are optional, last-exchange-
    only conversation memory (not a full thread — the frontend resends
    just the immediately preceding Q/A, never the whole session, to keep
    per-request token cost bounded; a deliberate scope choice, not a
    technical ceiling). Both None on the first question of a session, or
    whenever the frontend has no prior exchange to send. Threaded into
    both the classify and explain calls as real prior turns in the
    `messages` array (not spliced into either system prompt as text) —
    the standard, safest shape for giving a chat-completions API
    conversational context, and it sidesteps any prompt-injection-style
    risk a hand-built string insertion would carry.

    `previous_intent` is the intent that answered the previous question
    (echoed back from the prior AnswerResult.intent) — untrusted client
    input, never used directly, only ever checked for membership in
    _CONTINUABLE_INTENTS before being used to deterministically recover
    an unresolved follow-up (see the out_of_scope branch below).
    `previous_intents` is the same idea for every part of a multi-intent
    previous turn (echoed back from AnswerResult.intents) — purely
    additive, structural-only memory (not more Q/A text; see
    _first_continuable_intent): lets a follow-up after a compound answer
    still recover against any part of it, not just the first.

    A question that itself contains more than one distinct ask ("what's
    my revenue and what should I reorder") is answered as up to
    _MAX_SUBINTENTS separate parts in one response — see _build_part/
    _assemble_final_answer below — still using exactly one classify call
    and one explain call regardless of how many parts there are, to keep
    AI cost from scaling with how many things were asked.

    `all_branches` combines every business in business_id's group into
    one answer (app/application/business_group.py, same as the
    dashboard's own "Combine all branches" checkbox) — but a question
    naming one specific branch by itself always wins over it
    (_detect_named_business, deterministic, never classify-based): an
    explicit mention is more specific than a blanket toggle, the same
    way asking about one branch by name while browsing another
    business's chat page should still answer about the one actually
    named."""
    resolved_now = now or datetime.now(timezone.utc)

    # Zero-cost path: an obvious "what does X mean?" question never
    # touches the AI provider at all, and doesn't count against the
    # usage cap below.
    metric_key = match_definition_question(question)
    if metric_key is not None:
        return AnswerResult(answer=get_definition(metric_key) or _SAFE_FALLBACK, intent="metric_definition", grounded=True)

    settings = get_settings()
    request_repo = AIRequestRepository(db)
    if request_repo.count_today_for_business(business_id, now=resolved_now) >= settings.ai_daily_request_limit_per_business:
        return AnswerResult(answer=_USAGE_LIMIT_MESSAGE, intent="usage_limit_reached", grounded=True)

    business = db.get(Business, business_id)
    if business is None:
        return AnswerResult(answer=_SAFE_FALLBACK, intent="out_of_scope", grounded=True)

    # A question naming one of the account's own branches by name always
    # wins, even under all_branches — see _detect_named_business's own
    # docstring. Only ever matches a business the caller is actually a
    # member of (list_businesses_for_user is scoped to user_id), so this
    # can never leak another account's data.
    own_businesses = [b for b, _membership in list_businesses_for_user(db, user_id=user_id)]
    named_business = _detect_named_business(question, own_businesses)
    combined_businesses: list[Business] | None = None
    requested_all_branches = all_branches or _looks_like_all_branches_question(question)
    if named_business is not None:
        business = named_business
    elif requested_all_branches:
        try:
            combined_businesses = resolve_authorized_group(db, business_id=business_id, user_id=user_id)
        except NotGroupMember:
            return AnswerResult(answer=_SAFE_FALLBACK, intent="out_of_scope", grounded=True)
        except MixedTimezoneGroup as exc:
            return AnswerResult(
                answer=(
                    "Your branches don't all share one timezone ("
                    f"{', '.join(exc.timezones)}), so I can't combine them into one answer — "
                    "ask about one branch at a time instead."
                ),
                intent="out_of_scope",
                grounded=True,
            )

    # Live-reproduced real bug: asking "what's my revenue in Galway?"
    # correctly classified as financial_performance and correctly fetched
    # Galway-only data, but the explain call had no way to know the JSON
    # it was given was *already* scoped to Galway — nothing in the
    # context names a business at all — so it answered "I don't have a
    # location breakdown," 3/3 times reproduced live, even though the
    # figure it needed was right there. Every context payload now carries
    # an explicit scope label the explain prompt states outright, so the
    # model never has to guess whether what it's looking at is already
    # filtered.
    scope_label = (
        "Combined across: " + ", ".join(b.name for b in combined_businesses)
        if combined_businesses is not None
        else business.name
    )

    classify_list = _classify_intent(
        request_repo, business_id=business_id, user_id=user_id, question=question,
        business_timezone=business.timezone, now=resolved_now,
        previous_question=previous_question, previous_answer=previous_answer,
    )

    if len(classify_list) == 1 and classify_list[0].intent == "provider_unavailable":
        return AnswerResult(
            answer=_UNAVAILABLE_MESSAGE, intent="provider_unavailable", grounded=False,
            intents=("provider_unavailable",),
        )

    previous_intents_tuple = tuple(previous_intents) if previous_intents else ()
    parts = [
        _build_part(
            db, business=business, classify_item=item, now=resolved_now, combined_businesses=combined_businesses,
            question=question, previous_intent=previous_intent, previous_intents=previous_intents_tuple,
        )
        for item in classify_list
    ]
    all_intents = tuple(p.intent for p in parts)
    ai_parts = [(i, p) for i, p in enumerate(parts) if p.resolved_answer is None]

    if not ai_parts:
        # Every part resolved deterministically (a metric definition, a
        # lookup's 0/many-match message, a "no data for this" note, or an
        # unresolved out_of_scope refusal) — zero further AI cost, the
        # same fast paths this module already had for a single question,
        # now composed across up to _MAX_SUBINTENTS of them.
        final_answer = _join_parts_for_display([p.resolved_answer for p in parts])
        return AnswerResult(answer=final_answer, intent=parts[0].intent, grounded=True, intents=all_intents)

    if len(parts) == 1:
        # Single-intent path — the overwhelming majority of real
        # questions. Deliberately identical to this module's original
        # single-intent behavior (same system prompt, one explain call,
        # one guardrail call, no part markers) so nothing changes for the
        # common case just because multi-intent questions exist now.
        part = parts[0]
        answer_text = _generate_answer(
            request_repo, business_id=business_id, user_id=user_id, question=question, context=part.context,
            scope_label=scope_label, previous_question=previous_question, previous_answer=previous_answer,
        )
        if answer_text is None:
            # Tagged "provider_unavailable", not the already-classified
            # intent — this means the provider call itself never
            # completed (network/rate-limit/timeout) at the *explain*
            # step, not that whatever was classified genuinely failed to
            # produce an answer.
            return AnswerResult(
                answer=_UNAVAILABLE_MESSAGE, intent="provider_unavailable", grounded=False,
                intents=("provider_unavailable",),
            )

        result = validate_grounded(answer_text, part.context, question=question, previous_answer=previous_answer)
        if not result.grounded:
            logger.warning(
                "Ungrounded AI answer rejected business=%s intent=%s unsupported=%s",
                business_id, part.intent, result.unsupported_claims,
            )
            return AnswerResult(answer=_UNGROUNDED_FALLBACK, intent=part.intent, grounded=False, intents=(part.intent,))

        final_answer, links = _assemble_final_answer(
            [part], {0: answer_text}, question=question, previous_intent=previous_intent
        )
        return AnswerResult(answer=final_answer, intent=part.intent, grounded=True, links=links, intents=(part.intent,))

    # Multi-part path: the question genuinely asked more than one thing.
    # Only the parts that still need AI go into one merged explain call —
    # still exactly 2 AI calls total for the whole question (classify +
    # explain), never one per part, to keep cost bounded regardless of how
    # many things were asked. Numbered sequentially over just the
    # AI-needing subset (part_1, part_2, ...) — the model never needs to
    # know about a deterministically-resolved slot's position in the
    # original question.
    merged_context: dict[str, Any] = {}
    part_index_by_key: dict[str, int] = {}
    already_answered = [
        {"already_answered_part": i + 1, "answer": p.resolved_answer}
        for i, p in enumerate(parts) if p.resolved_answer is not None
    ]
    for position, (i, p) in enumerate(ai_parts, start=1):
        key = f"part_{position}"
        merged_context[key] = {
            "focus": _INTENT_FOCUS_LABELS.get(p.intent, p.intent), "intent": p.intent, "data": p.context,
        }
        part_index_by_key[key] = i
    if already_answered:
        # Given to the model as context only (so it doesn't re-answer, or
        # contradict, a part that already has its own final answer) — not
        # something the model is asked to reproduce.
        merged_context["_already_answered"] = already_answered

    answer_text = _generate_answer(
        request_repo, business_id=business_id, user_id=user_id, question=question, context=merged_context,
        scope_label=scope_label, previous_question=previous_question, previous_answer=previous_answer,
        multi_part=True,
    )
    if answer_text is None:
        return AnswerResult(
            answer=_UNAVAILABLE_MESSAGE, intent="provider_unavailable", grounded=False,
            intents=("provider_unavailable",),
        )

    segments = _split_multi_part_answer(answer_text, expected_parts=len(ai_parts))
    if segments is None:
        # Fail closed, same posture as every other "don't trust the
        # model's exact output shape" spot in this module: the model
        # didn't follow the marker instruction cleanly, so parts can't be
        # told apart reliably — fall back to one whole-answer guardrail
        # check instead of risking a misattributed split. Markers are
        # stripped either way so a stray one is never shown to the user.
        cleaned = _PART_MARKER_PATTERN.sub("", answer_text).strip()
        result = validate_grounded(cleaned, merged_context, question=question, previous_answer=previous_answer)
        ai_text = cleaned if result.grounded else _UNGROUNDED_FALLBACK
        if not result.grounded:
            logger.warning(
                "Ungrounded multi-part AI answer rejected (coarse fallback) business=%s intents=%s unsupported=%s",
                business_id, all_intents, result.unsupported_claims,
            )
        resolved_texts = [p.resolved_answer for p in parts if p.resolved_answer is not None]
        final_answer = _join_parts_for_display([*resolved_texts, ai_text])
        contexts = [p.context for p in parts if p.context is not None]
        final_answer = _append_truncation_disclosure(final_answer, contexts)
        links = ("dashboard", "reports") if _find_shown_of_total_notes(contexts) else ()
        return AnswerResult(
            answer=final_answer, intent=parts[0].intent, grounded=result.grounded, links=links, intents=all_intents,
        )

    ai_text_by_index: dict[int, str] = {}
    any_segment_failed = False
    for key, part_index in part_index_by_key.items():
        n = int(key.rsplit("_", 1)[1])
        segment_text = segments.get(n)
        part = parts[part_index]
        if segment_text is None:
            ai_text_by_index[part_index] = _UNGROUNDED_FALLBACK
            any_segment_failed = True
            continue
        result = validate_grounded(segment_text, part.context, question=question, previous_answer=previous_answer)
        if result.grounded:
            ai_text_by_index[part_index] = segment_text
        else:
            logger.warning(
                "Ungrounded AI answer rejected for one part business=%s intent=%s unsupported=%s",
                business_id, part.intent, result.unsupported_claims,
            )
            ai_text_by_index[part_index] = _UNGROUNDED_FALLBACK
            any_segment_failed = True

    final_answer, links = _assemble_final_answer(
        parts, ai_text_by_index, question=question, previous_intent=previous_intent
    )
    return AnswerResult(
        answer=final_answer, intent=parts[0].intent, grounded=not any_segment_failed, links=links, intents=all_intents,
    )


_INTENT_FOCUS_LABELS = {
    "financial_performance": "revenue and margin",
    "retail_operations": "retail/stock overview",
    "workshop_performance": "workshop/repairs performance",
    "forecast": "demand forecast and reorder suggestions",
    "findings_recommendations": "flagged issues and recommendations",
    "category_breakdown": "revenue/cost by category",
    "purchase_history": "purchase/order history",
    "product_lookup": "a specific product",
    "purchase_lookup": "a specific purchase/order",
    "repair_lookup": "a specific repair",
    "latest_report": "the latest report",
}


def _first_continuable_intent(previous_intent: str | None, previous_intents: tuple[str, ...]) -> str | None:
    """The first of the previous turn's intent(s) that's safe to silently
    continue on an unresolved follow-up (_CONTINUABLE_INTENTS) — checks
    the singular previous_intent first (today's existing single-turn
    behavior, unchanged), then falls through to the rest of a multi-part
    previous turn. Returns None if nothing continuable is found, same
    fail-closed default as before this existed."""
    if previous_intent in _CONTINUABLE_INTENTS:
        return previous_intent
    for candidate in previous_intents:
        if candidate in _CONTINUABLE_INTENTS:
            return candidate
    return None


def _recover_out_of_scope_intent(
    question: str, previous_intent: str | None, previous_intents: tuple[str, ...] = ()
) -> str | None:
    """Defense in depth against classify unreliability (free-tier model
    variance) — live fire-test evidence: a reorder/stock-out-shaped
    question ("what's going to run out of stock", "what should I spend
    €2,000 on restocking") occasionally came back out_of_scope even
    though the classify prompt's own "forecast" description explicitly
    covers this exact question shape; a "what/when was the previous
    period?" or "merge/combine/total" follow-up occasionally came back
    out_of_scope despite a clear prior exchange to resolve against. Only
    ever promotes out_of_scope -> a specific real intent using the same
    deterministic keyword checks already built for the priority-list
    feature and the period/aggregate follow-up recovery — can never grant
    a more sensitive intent or override a genuine out-of-scope verdict
    for anything else, so this only recovers real questions, never
    weakens the refusal path itself. Returns the recovered intent name,
    or None if classify's out_of_scope verdict should stand (the caller
    then returns the same safe refusal as always)."""
    if _looks_like_purchase_history_question(question):
        return "purchase_history"
    if _looks_like_a_reorder_question(question) or (
        _looks_like_branch_split_question(question)
        and (previous_intent == "forecast" or "forecast" in previous_intents)
    ):
        return "forecast"
    # Second, narrower recovery net, same shape as the reorder one above:
    # a period/aggregate follow-up only makes sense in light of whatever
    # was just discussed — recover to that exact intent (validated
    # against the fixed _CONTINUABLE_INTENTS allow-list via
    # _first_continuable_intent, never trusted as client input past that
    # membership check) rather than guessing a default. No continuable
    # previous intent -> falls through to the same safe refusal as any
    # other unresolved out_of_scope, never guessed.
    continuable = _first_continuable_intent(previous_intent, previous_intents)
    if continuable is not None and (
        _looks_like_a_period_follow_up_question(question) or _looks_like_aggregate_follow_up_question(question)
    ):
        return continuable
    return None


def _build_part(
    db: Session,
    *,
    business: Business,
    classify_item: ClassifyResult,
    now: datetime,
    combined_businesses: list[Business] | None,
    question: str,
    previous_intent: str | None,
    previous_intents: tuple[str, ...],
) -> _Part:
    """Resolves one classify sub-intent into either a final, zero-AI-cost
    answer (_Part.resolved_answer) or the context the shared explain call
    needs (_Part.context) — the same per-intent dispatch answer_question
    always did for the whole question, now reusable per sub-question. See
    answer_question's own docstring for how the results compose."""
    intent = classify_item.intent

    if intent == "out_of_scope":
        recovered = _recover_out_of_scope_intent(question, previous_intent, previous_intents)
        if recovered is None:
            return _Part(intent="out_of_scope", resolved_answer=_SAFE_FALLBACK)
        # Only period/start_date/end_date carry over — metric/search_term/
        # horizon_days were extracted (if at all) for whatever intent
        # classify originally, wrongly, picked, and don't necessarily
        # mean anything for the recovered one.
        classify_item = ClassifyResult(
            intent=recovered, period=classify_item.period, start_date=classify_item.start_date,
            end_date=classify_item.end_date,
        )
        intent = recovered

    if intent == "metric_definition":
        definition = get_definition(classify_item.metric) if classify_item.metric else None
        return _Part(intent="metric_definition", resolved_answer=definition or _SAFE_FALLBACK)

    if intent in ("product_lookup", "purchase_lookup", "repair_lookup"):
        context, early_result = _dispatch_lookup(
            db, business=business, intent=intent, classify=classify_item, question=question
        )
        if early_result is not None:
            # early_result.intent is not always `intent` itself — a
            # product_lookup with no search_term at all comes back as
            # "out_of_scope" specifically (see _dispatch_lookup), not
            # "product_lookup" — preserve whichever it actually is.
            return _Part(intent=early_result.intent, resolved_answer=early_result.answer)
        return _Part(intent=intent, context=context)

    context = _fetch_context(
        db, business=business, intent=intent, classify=classify_item, now=now, combined_businesses=combined_businesses,
    )
    if context is None:
        # Not applicable (e.g. workshop performance for a non-bike-shop
        # template, or no report exists yet) — same safe fallback, zero
        # further AI cost for this part.
        return _Part(intent=intent, resolved_answer=_SAFE_FALLBACK)
    # Set aside for the deterministic priority-list builder in
    # _assemble_final_answer, then stripped before the LLM ever sees this
    # dict — the *complete* reorder list costs nothing extra (it's local
    # formatting, not another AI call), so it doesn't need the same
    # cost-driven cap as what actually goes in the prompt (see
    # _MAX_CONTEXT_ROWS).
    all_products = context.pop("_all_products_for_priority_list", None)
    return _Part(intent=intent, context=context, all_products_for_priority_list=all_products)


def _join_parts_for_display(texts: list[str]) -> str:
    """Joins final part texts into one ORLA message — a single element
    passes through completely unchanged (so the single-intent path stays
    byte-for-byte identical to before multi-part answers existed)."""
    return "\n\n".join(t for t in texts if t)


# The marker the explain step is told to prefix each part's own answer
# with (see _MULTI_PART_INSTRUCTION) — deliberately not plain text like
# "Part 1:", which could plausibly appear in a legitimate answer on its
# own and be split on by accident; these bracket characters are not
# something a real business-data answer would ever otherwise contain.
_PART_MARKER_PATTERN = re.compile("⟦PART_(\\d+)⟧")


def _split_multi_part_answer(answer_text: str, *, expected_parts: int) -> dict[int, str] | None:
    """Splits a multi-part explain answer on its own marker into
    {part_number: text}, 1-based matching the part_N keys the merged
    context was built with. Fails closed (returns None) on anything other
    than exactly one clean, in-range, non-duplicate marker per expected
    part — a malformed split could otherwise silently attribute one
    part's text to the wrong part's data during guardrail validation,
    defeating the point of validating per part at all. The caller falls
    back to a coarser whole-answer check when this happens."""
    matches = list(_PART_MARKER_PATTERN.finditer(answer_text))
    if len(matches) != expected_parts:
        return None
    seen: set[int] = set()
    result: dict[int, str] = {}
    for i, m in enumerate(matches):
        n = int(m.group(1))
        if n in seen or n < 1 or n > expected_parts:
            return None
        seen.add(n)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(answer_text)
        result[n] = answer_text[start:end].strip()
    return result


def _assemble_final_answer(
    parts: list[_Part], ai_text_by_index: dict[int, str], *, question: str, previous_intent: str | None,
) -> tuple[str, tuple[str, ...]]:
    """Reassembles the final user-facing answer from every part, in the
    original question order — a resolved_answer part's text is already
    final; an AI-answered part's text comes from ai_text_by_index (already
    guardrail-checked by the caller). Also where the existing
    deterministic priority-order list (_build_priority_order_list) gets
    attached to whichever part is actually the forecast/reorder one, and
    where the existing truncation-disclosure/links logic runs — both
    reused unchanged, just now over every part's context rather than one.
    For a single part this reduces to exactly the original single-
    question assembly, byte-for-byte."""
    wants_reorder_list = _looks_like_a_reorder_question(question) or (
        _looks_like_branch_split_question(question) and previous_intent == "forecast"
    )
    texts: list[str] = []
    contexts_for_links: list[dict] = []
    for i, part in enumerate(parts):
        if part.resolved_answer is not None:
            texts.append(part.resolved_answer)
            continue
        text = ai_text_by_index[i]
        if part.intent == "forecast" and wants_reorder_list and part.all_products_for_priority_list:
            built = _build_priority_order_list(
                part.all_products_for_priority_list, group_by_business=_looks_like_branch_split_question(question)
            )
            if built is not None:
                priority_list, list_itself_truncated = built
                text = f"{text}\n\n{priority_list}"
                if not list_itself_truncated and part.context is not None:
                    # The priority list above already answers "what do I
                    # need to order" completely (it's built from the
                    # untrimmed product list, not the LLM's capped view)
                    # — the generic "only 15 of 152 shown" note would be
                    # confusing noise right next to an answer that isn't
                    # partial. If the priority list itself had to
                    # truncate, the note and links stay — genuinely still
                    # a partial answer.
                    part.context.pop("products_shown_of_total", None)
        texts.append(text)
        if part.context is not None:
            contexts_for_links.append(part.context)

    joined = _join_parts_for_display(texts)
    joined = _append_truncation_disclosure(joined, contexts_for_links)
    links = ("dashboard", "reports") if _find_shown_of_total_notes(contexts_for_links) else ()
    return joined, links


def _find_shown_of_total_notes(context: Any) -> list[str]:
    """Every `{field}_shown_of_total` note anywhere in a (possibly
    nested, e.g. a stored report's) context — added by _cap_rows
    whenever a list got truncated for cost reasons."""
    notes: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("_shown_of_total") and isinstance(value, str):
                    notes.append(f"{key[: -len('_shown_of_total')]}: {value}")
                else:
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(context)
    return notes


def _append_truncation_disclosure(answer_text: str, context: Any) -> str:
    """Guarantees the "this is a partial list" disclosure always appears
    whenever a list was actually capped — as a deterministic append, not
    a prompt instruction the model might skip. Live-verified this
    matters: asked to "give the full list," the model answered
    correctly from the shown rows but simply didn't mention that 152
    products existed and only 15 were shown — a prompt is a hint, not a
    guarantee, exactly the same reasoning behind the numeric guardrail
    itself."""
    notes = _find_shown_of_total_notes(context)
    if not notes:
        return answer_text
    return f"{answer_text} (Showing {'; '.join(notes)} — see the Dashboard or Reports page for the complete list.)"


_REORDER_KEYWORDS = (
    "order", "reorder", "restock", "buy", "purchase", "stock up",
    # Added after a live fire-test run showed "run out of stock"-shaped
    # questions occasionally misclassified as out_of_scope despite the
    # classify prompt's own "forecast" description explicitly covering
    # them (free-tier model variance, not a prompt gap) — see
    # answer_question's out_of_scope recovery below.
    "run out", "stock out", "stockout",
)


_PURCHASE_HISTORY_KEYWORDS = (
    "last orders", "latest orders", "recent orders", "order history", "purchase history", "last purchases",
    "latest purchases", "recent purchases", "things i ordered", "items i ordered", "most expensive things i ordered",
    "most expensive items i ordered", "most expensive purchases", "unit cost", "by unit",
)


def _looks_like_purchase_history_question(question: str) -> bool:
    lowered = question.lower()
    return any(keyword in lowered for keyword in _PURCHASE_HISTORY_KEYWORDS)


def _looks_like_a_reorder_question(question: str) -> bool:
    """A cheap, deterministic check gating the priority-list build below
    — the `forecast` intent's context also covers plain revenue-forecast
    questions ("what's next week looking like?"), which shouldn't get an
    unrelated product-reorder list appended."""
    lowered = question.lower()
    return any(keyword in lowered for keyword in _REORDER_KEYWORDS)


_BRANCH_SPLIT_KEYWORDS = (
    "split", "separate", "breakdown", "break down", "branch", "branches", "shop", "shops", "location",
)


def _looks_like_branch_split_question(question: str) -> bool:
    lowered = question.lower()
    return any(keyword in lowered for keyword in _BRANCH_SPLIT_KEYWORDS)


# Intents safe to silently continue on an unresolved follow-up — every
# one of these is a whole-topic aggregate where "same topic, a different
# angle on it" is a safe assumption to make without the classify step's
# own judgment. Deliberately excludes: metric_definition/out_of_scope/
# provider_unavailable/usage_limit_reached (not real data topics to
# continue); product_lookup/purchase_lookup/repair_lookup (continuing
# one of these blindly would mean re-running a lookup with a stale
# search_term and no new one — those already have their own
# disambiguation flow via app/application/lookups.py, a silent intent
# swap here would only make that worse, not better).
_CONTINUABLE_INTENTS = frozenset(
    {
        "financial_performance",
        "retail_operations",
        "workshop_performance",
        "forecast",
        "findings_recommendations",
        "category_breakdown",
        "latest_report",
    }
)

# Live-verified real, repeated bug: three separate transcripts, three
# different phrasings ("what was the previous period?", "when was the
# previous period?", "what is the last period?"), all classified
# out_of_scope despite a clear prior exchange to resolve against — a
# prompt-only fix (telling the classify model to infer the same intent
# as the previous turn) held for the one exact phrasing it was tuned
# against and failed to generalise to the others on this free-tier
# model. This is the same "don't trust the model to reliably do this,
# build a deterministic net instead" reasoning as the reorder recovery
# above, extended to the one other question shape that's now shown up
# three times independently.
_PERIOD_FOLLOW_UP_KEYWORDS = (
    "previous period", "last period", "prior period", "the period before",
    "that period", "this period", "which period", "what period",
)


def _looks_like_a_period_follow_up_question(question: str) -> bool:
    lowered = question.lower()
    return any(keyword in lowered for keyword in _PERIOD_FOLLOW_UP_KEYWORDS)


_AGGREGATE_FOLLOW_UP_KEYWORDS = (
    "merge", "merged", "combine", "combined", "total", "overall", "together", "sum", "add them", "add those",
    "full business", "whole business", "entire business", "full company", "whole company", "all together",
)


def _looks_like_aggregate_follow_up_question(question: str) -> bool:
    lowered = question.lower()
    return any(keyword in lowered for keyword in _AGGREGATE_FOLLOW_UP_KEYWORDS)


def _detect_named_business(question: str, businesses: list[Business]) -> Business | None:
    """Deterministic, not LLM-based — direct scope decision: a question
    naming one of the account's own branches by name ("what was revenue
    at the Galway branch?") should answer about that branch specifically,
    regardless of whatever business the chat page happens to be scoped
    to. Reuses the exact same "don't trust the model to reliably do this"
    reasoning as the reorder/period-follow-up recovery above — the
    classify prompt already regressed twice this session from growing
    too large for its own token budget, so this never touches it.

    Whole-word, case-insensitive matching (not a bare substring) against
    each business's real `name` — guards against a short/generic name
    accidentally matching inside an unrelated word. Returns None (no
    override) if zero or more than one distinct business matches; an
    ambiguous match falls through to whatever scope was already
    selected rather than guessing between two real candidates.
    """
    lowered = question.lower()
    matches = [
        business
        for business in businesses
        if business.name and re.search(rf"\b{re.escape(business.name.lower())}\b", lowered)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


_ALL_BRANCHES_PATTERNS = (
    r"\bacross\s+(?:all|both|my|our)\s+(?:branches|shops|locations)\b",
    r"\b(?:all|both|my|our)\s+(?:branches|shops|locations)\b",
    r"\b(?:two|2)\s+(?:branches|shops|locations)\b",
)


def _looks_like_all_branches_question(question: str) -> bool:
    lowered = question.lower()
    return any(re.search(pattern, lowered) for pattern in _ALL_BRANCHES_PATTERNS)


# Zero-cost — this is local formatting after the AI calls are already
# done, not another prompt — so it can afford to be far more generous
# than _MAX_CONTEXT_ROWS (which bounds what's actually sent to the
# model). Still bounded, because a 100-line chat message is bad UX
# regardless of cost.
_MAX_PRIORITY_LIST_DISPLAY = 30


def _format_priority_product_line(index: int, product: dict) -> str:
    name = product.get("name", "Unknown product")
    quantity = product.get("suggested_reorder_quantity")
    cover = product.get("days_of_cover_at_forecast_rate")
    cover_note = f" ({cover} days cover left)" if cover is not None else ""
    return f"{index}. {name} — {quantity} units{cover_note}"


def _build_priority_order_list(all_products: list, *, group_by_business: bool = False) -> tuple[str, bool] | None:
    """Deterministically formats every product needing reorder, in
    guaranteed urgency order (get_forecast's own docstring: products are
    already sorted soonest-out-of-stock-first) — not left to the model's
    prose, which live testing showed doesn't reliably preserve order or
    completeness. Directly requested: "order them based on what is
    needed more urgently, as this is more valuable." Built from the
    *untrimmed* product list (see answer_question), so — unlike the
    model's own view — this is genuinely complete unless it itself
    exceeds _MAX_PRIORITY_LIST_DISPLAY.

    Returns (formatted_text, was_truncated), or None if nothing needs
    reordering — `was_truncated` tells the caller whether to still point
    to the Dashboard for the rest, even though this list is otherwise a
    complete answer on its own.
    """
    to_order = [p for p in all_products if isinstance(p, dict) and (p.get("suggested_reorder_quantity") or 0) > 0]
    if not to_order:
        return None

    if group_by_business and any(product.get("business_name") for product in to_order):
        lines = ["Priority order by branch (most urgent first):"]
        shown = 0
        truncated = len(to_order) > _MAX_PRIORITY_LIST_DISPLAY
        grouped: dict[str, list[dict]] = {}
        for product in to_order:
            branch = product.get("business_name") or "Unknown branch"
            grouped.setdefault(branch, []).append(product)
        for branch, products in grouped.items():
            if shown >= _MAX_PRIORITY_LIST_DISPLAY:
                break
            lines.append(f"{branch}:")
            for product in products:
                if shown >= _MAX_PRIORITY_LIST_DISPLAY:
                    break
                shown += 1
                lines.append(_format_priority_product_line(shown, product))
        remaining = len(to_order) - shown
        if remaining > 0:
            lines.append(f"...and {remaining} more product(s) need reordering — see the Dashboard for the full list.")
        return "\n".join(lines), truncated

    lines = []
    for i, product in enumerate(to_order[:_MAX_PRIORITY_LIST_DISPLAY], start=1):
        lines.append(_format_priority_product_line(i, product))

    remaining = len(to_order) - len(lines)
    truncated = remaining > 0
    if truncated:
        lines.append(f"...and {remaining} more product(s) need reordering — see the Dashboard for the full list.")

    return "Priority order (most urgent first):\n" + "\n".join(lines), truncated


def _resolve_dates(business: Business, classify: ClassifyResult, now: datetime) -> tuple[date | None, date | None]:
    if classify.period == "explicit_date":
        # Already server-side validated in _parse_intent_json (parsed,
        # start<=end, within sane bounds) — never trusted straight off
        # the model beyond that point.
        return classify.start_date, classify.end_date
    if classify.period == "last_completed_week":
        return compute_report_period(business.timezone, "weekly", now=now)
    if classify.period == "last_completed_month":
        return compute_report_period(business.timezone, "monthly", now=now)
    return None, None  # default_recent — same unset-range default the dashboard uses


# One example phrasing per lookup intent, used only to fill in the
# many-match disambiguation message below — {label} is substituted with
# the first real match's own label, so the example always names a real
# product/purchase/repair from this business, not a generic placeholder.
_LOOKUP_EXAMPLE_PHRASING = {
    "product_lookup": "how much stock of {label} do I have",
    "purchase_lookup": "what did I order under {label}",
    "repair_lookup": "how much did the repair {label} cost",
}

# Live-reproduced real transcript: "what did I order under E-Motion
# Trail 500 3 in my last order?" — the search term itself unambiguously
# named one product with a real multi-order history (see LookupResult.
# resolved_rows), and this phrasing is what actually narrows "give me
# the whole history" down to "just the most recent one." Deterministic,
# same reasoning as every other keyword net in this module — classify
# already has enough to do extracting the search term itself.
_LAST_ORDER_ONLY_KEYWORDS = (
    "last order", "last time", "last purchase", "last delivery",
    "most recent order", "most recent purchase", "most recent delivery",
    "latest order", "latest purchase", "latest delivery",
)


def _looks_like_last_order_only_question(question: str) -> bool:
    lowered = question.lower()
    return any(keyword in lowered for keyword in _LAST_ORDER_ONLY_KEYWORDS)


def _dispatch_lookup(
    db: Session, *, business: Business, intent: str, classify: ClassifyResult, question: str
) -> tuple[dict | None, AnswerResult | None]:
    """Shared 0/1/many-match handling for the three per-record lookup
    intents. Returns (context, None) on exactly one match — the caller
    proceeds through the normal explain -> guardrail pipeline, same as
    every other intent. Returns (None, AnswerResult) for the 0- or
    many-match cases: a final, deterministic answer with zero further
    AI cost — a wrong silent guess here is exactly what the guardrail
    elsewhere in this module exists to prevent, so ambiguity is always
    surfaced, never resolved by picking the first match."""
    if intent == "product_lookup":
        if not classify.search_term:
            return None, AnswerResult(answer=_SAFE_FALLBACK, intent="out_of_scope", grounded=True)
        result = find_products(db, business_id=business.id, query=classify.search_term)
    elif intent == "purchase_lookup":
        result = find_purchases(
            db, business_id=business.id, search_term=classify.search_term,
            start_date=classify.start_date, end_date=classify.end_date,
        )
    elif intent == "repair_lookup":
        result = find_repairs(
            db, business_id=business.id, business_timezone=business.timezone, search_term=classify.search_term,
            start_date=classify.start_date, end_date=classify.end_date,
        )
    else:
        return None, AnswerResult(answer=_SAFE_FALLBACK, intent="out_of_scope", grounded=True)

    # Live-reproduced real bug, a different transcript from the
    # match_labels one below: a search term can unambiguously identify
    # ONE thing (a specific product, or a specific PO reference) that
    # legitimately has more than one row to report — a product's full
    # order history, or several line items under one PO. That's a
    # complete multi-row answer, never routed through the 0/1/many
    # disambiguation below at all (see LookupResult.resolved_rows's own
    # docstring for the exact reported transcript this closes).
    if result.resolved_rows is not None:
        rows = result.resolved_rows
        if intent == "purchase_lookup" and len(rows) > 1 and _looks_like_last_order_only_question(question):
            rows = rows[:1]
        if len(rows) == 1:
            return rows[0], None
        return {"matches": rows}, None

    # Live-reproduced real bug: find_purchases's own "search term matched
    # several products, which one?" branch (app/application/lookups.py)
    # populates match_labels but deliberately leaves matches empty (it
    # has no single resolved purchase record yet, only candidate product
    # identities) — checking `result.matches` here treated that
    # genuinely-ambiguous case as "nothing found" instead of "several
    # things found," which is the opposite of what actually happened.
    # match_labels is always populated whenever there's anything to
    # report at all (every LookupResult-returning function keeps it in
    # lockstep with matches except that one case), so it's the correct
    # single source of truth for "how many candidates," not matches.
    if not result.match_labels:
        term = classify.search_term or "that"
        message = f'I couldn\'t find anything matching "{term}" in your data.'
        return None, AnswerResult(answer=message, intent=intent, grounded=True)

    if len(result.match_labels) > 1:
        listed = "; ".join(result.match_labels[:5])
        # Explicitly models a full, self-contained follow-up question
        # rather than just saying "be more specific" — ORLA has no
        # conversation memory between messages (a stated, deliberate
        # limitation to keep token cost down), so a reply that's just
        # the bare item name/label (the natural thing to do after being
        # shown a list) isn't a question the classify step has much to
        # work with. Live-verified this matters: the model *usually*
        # still resolves a bare label correctly, but it's a fragile,
        # not-guaranteed shape to rely on — showing the example phrasing
        # up front is a cheap, real improvement that doesn't require
        # building actual multi-turn memory.
        example = _LOOKUP_EXAMPLE_PHRASING[intent].format(label=result.match_labels[0])
        message = (
            f"I found several matching results: {listed}. Ask me again naming just the one you mean — "
            f'for example, "{example}?"'
        )
        return None, AnswerResult(answer=message, intent=intent, grounded=True)

    return result.matches[0], None


def _fetch_context(
    db: Session,
    *,
    business: Business,
    intent: str,
    classify: ClassifyResult,
    now: datetime,
    combined_businesses: list[Business] | None = None,
) -> dict | None:
    """`combined_businesses`, when set (answer_question's all_branches
    path, never set together with a named-branch override — see its own
    docstring), only applies to the five intents that also support it on
    the dashboard (app/api/analytics.py's own all_branches scope):
    financial/retail/workshop/forecast/findings. category_breakdown and
    latest_report stay single-business regardless — a stored report
    belongs to one business's own row (no "combined report" concept
    exists), and category_breakdown was never offered in combined form
    on the dashboard either, so chat doesn't invent a wider scope for it
    than the UI it mirrors already has.
    """
    business_id = business.id
    start_date, end_date = _resolve_dates(business, classify, now)

    if intent == "financial_performance":
        if combined_businesses is not None:
            summary = get_financial_performance_for_group(
                db, businesses=combined_businesses, start_date=start_date, end_date=end_date
            )
            context = FinancialPerformanceOut.model_validate(summary).model_dump(mode="json")
            context["branches"] = [
                _financial_branch_context(
                    business,
                    get_financial_performance(
                        db, business_id=business.id, start_date=start_date, end_date=end_date
                    ),
                )
                for business in combined_businesses
            ]
            return context
        else:
            summary = get_financial_performance(db, business_id=business_id, start_date=start_date, end_date=end_date)
        return FinancialPerformanceOut.model_validate(summary).model_dump(mode="json")
    if intent == "retail_operations":
        if combined_businesses is not None:
            summary = get_retail_operations_for_group(
                db, businesses=combined_businesses, start_date=start_date, end_date=end_date
            )
        else:
            summary = get_retail_operations(db, business_id=business_id, start_date=start_date, end_date=end_date)
        return _trim_retail_operations(RetailOperationsOut.model_validate(summary).model_dump(mode="json"))
    if intent == "workshop_performance":
        if business.template != "bicycle_shop":
            return None
        if combined_businesses is not None:
            summary = get_workshop_performance_for_group(
                db, businesses=combined_businesses, start_date=start_date, end_date=end_date
            )
        else:
            summary = get_workshop_performance(db, business_id=business_id, start_date=start_date, end_date=end_date)
        return WorkshopPerformanceOut.model_validate(summary).model_dump(mode="json")
    if intent == "forecast":
        horizon_days = classify.horizon_days or _DEFAULT_HORIZON_DAYS
        if combined_businesses is not None:
            summary = get_forecast_for_group(db, businesses=combined_businesses, now=now, horizon_days=horizon_days)
        else:
            summary = get_forecast(db, business_id=business_id, now=now, horizon_days=horizon_days)
        full = ForecastOut.model_validate(summary).model_dump(mode="json")
        trimmed = _trim_forecast(full)
        # Stashed for answer_question's deterministic priority-list
        # builder, then popped before this dict ever reaches the LLM
        # (see answer_question) — the full, untrimmed list costs nothing
        # extra since it's local formatting, not another AI call.
        trimmed["_all_products_for_priority_list"] = full.get("products", [])
        return trimmed
    if intent == "findings_recommendations":
        if combined_businesses is not None:
            summary = get_findings_for_group(db, businesses=combined_businesses, start_date=start_date, end_date=end_date)
        else:
            summary = get_findings(db, business_id=business_id, start_date=start_date, end_date=end_date)
        return _trim_findings(FindingsOut.model_validate(summary).model_dump(mode="json"))
    if intent == "category_breakdown":
        summary = get_category_breakdown(db, business_id=business_id, start_date=start_date, end_date=end_date)
        return _trim_category_breakdown(CategoryBreakdownOut.model_validate(summary).model_dump(mode="json"))
    if intent == "purchase_history":
        return _purchase_history_context(db, businesses=combined_businesses or [business])
    if intent == "latest_report":
        reports = ReportRepository(db).list_active_for_business(business_id, now=now)
        if not reports:
            return None
        return _trim_report_payload(reports[0].payload)
    return None


# Live-verified this matters, not theoretical: a real business's forecast
# context alone was 141,660 characters (152 products x a 7-day daily
# breakdown each), and its stored report payload — which nests the same
# forecast plus a stock-cover row per product — was 300,573 characters.
# That's a large, expensive prompt for every single question, directly
# against the stated "keep tokens/cost as low as possible" priority, and
# on some models leaves too little of the token budget for an actual
# answer to be produced at all. These caps mirror the dashboard's own
# display cap (frontend/app/dashboard/page.tsx's `.slice(0, 15)` for the
# forecast table and stock-cover chart) — applied before the data ever
# reaches the model, not only at render time.
_MAX_CONTEXT_ROWS = 15


def _cap_rows(trimmed: dict, key: str) -> None:
    """Caps `trimmed[key]` to _MAX_CONTEXT_ROWS in place — and, only
    when truncation actually happens, adds a sibling `{key}_shown_of_
    total` note. Capping alone would silently risk a confidently wrong
    aggregate answer ("you have 4 low-stock products") when the true
    count is much higher: every individual number in a capped list is
    still grounded, but the implied completeness wouldn't be true. The
    note gives the model something real to disclose instead (its own
    numbers are automatically grounded too — they're now literally in
    the context). See orla_constitution.md for the matching instruction
    to actually say so and point to the full list elsewhere.
    """
    rows = trimmed.get(key)
    if not isinstance(rows, list):
        return
    total = len(rows)
    if total > _MAX_CONTEXT_ROWS:
        trimmed[f"{key}_shown_of_total"] = f"{_MAX_CONTEXT_ROWS} of {total}"
    trimmed[key] = rows[:_MAX_CONTEXT_ROWS]


def _trim_forecast_result(result: dict) -> dict:
    # The day-by-day curve is chart-only data (frontend/lib/chartOptions
    # .ts's revenueForecastLineOption) — a text answer only ever needs
    # the aggregate total_point/total_low/total_high.
    return {k: v for k, v in result.items() if k != "daily"}


def _financial_branch_context(business: Business, summary: Any) -> dict:
    """Small branch breakdown for combined financial chat answers.
    The combined summary remains the dashboard-equivalent total; this
    branch list gives ORLA already-computed per-business figures when the
    user asks for profit/revenue across "two branches" or "both shops"."""
    data = FinancialPerformanceOut.model_validate(summary).model_dump(mode="json")
    return {
        "business_id": str(business.id),
        "business_name": business.name,
        "revenue": data["revenue"],
        "gross_margin": data["gross_margin"],
        "returns": data["returns"],
    }


def _purchase_history_context(db: Session, *, businesses: list[Business]) -> dict:
    recent_rows = []
    expensive_rows = []
    for business in businesses:
        repo = InventoryMovementRepository(db)
        recent, _total = repo.list_purchases_paginated(business.id, limit=_MAX_CONTEXT_ROWS)
        recent_rows.extend(_purchase_context_row(business, movement, product, supplier) for movement, product, supplier in recent)
        expensive_rows.extend(
            _purchase_context_row(business, movement, product, supplier)
            for movement, product, supplier in repo.list_purchases_by_unit_cost(business.id, limit=_MAX_CONTEXT_ROWS)
        )

    recent_rows.sort(key=lambda row: (row["event_date"] or "", row["purchase_id"]), reverse=True)
    expensive_rows.sort(
        key=lambda row: (
            row["unit_cost"] is not None,
            Decimal(row["unit_cost"]) if row["unit_cost"] is not None else Decimal("0"),
            row["event_date"] or "",
        ),
        reverse=True,
    )
    return {
        "recent_purchases": recent_rows[:_MAX_CONTEXT_ROWS],
        "most_expensive_unit_purchases": expensive_rows[:_MAX_CONTEXT_ROWS],
    }


def _purchase_context_row(business: Business, movement: Any, product: Any, supplier: Any) -> dict:
    return {
        "purchase_id": str(movement.id),
        "business_id": str(business.id),
        "business_name": business.name,
        "product_id": str(movement.product_id),
        "product_name": product.name if product else "Unknown product",
        "sku": product.sku if product else None,
        "supplier_name": supplier.name if supplier else None,
        "quantity_received": movement.quantity_delta,
        "purchase_reference": movement.purchase_reference,
        "event_date": movement.event_date.isoformat() if movement.event_date else None,
        "unit_cost": str(movement.unit_cost) if movement.unit_cost is not None else None,
    }


def _trim_forecast(forecast: dict) -> dict:
    trimmed = dict(forecast)
    revenue = trimmed.get("revenue")
    if isinstance(revenue, dict) and isinstance(revenue.get("result"), dict):
        trimmed["revenue"] = {**revenue, "result": _trim_forecast_result(revenue["result"])}
    # Already sorted soonest-out-of-stock first (get_forecast's own
    # docstring) — capping keeps the most urgent, not an arbitrary slice.
    _cap_rows(trimmed, "products")
    trimmed["products"] = [
        {**p, "result": _trim_forecast_result(p["result"])} if isinstance(p.get("result"), dict) else p
        for p in trimmed["products"]
    ]
    return trimmed


def _trim_retail_operations(retail: dict) -> dict:
    trimmed = dict(retail)
    # Already sorted soonest-out-of-stock first (build_stock_cover_
    # report's own docstring).
    _cap_rows(trimmed, "stock_cover")
    # A blunt size bound, not a relevance-ranked cap — dead stock isn't
    # sorted by the analytics layer today. Bounding prompt size still
    # matters even without perfect prioritisation.
    _cap_rows(trimmed, "dead_stock")
    return trimmed


def _trim_findings(findings: dict) -> dict:
    trimmed = dict(findings)
    # Already severity/impact-ranked (C10's evaluate_all/
    # build_recommendations) — capping keeps the most important, not an
    # arbitrary slice.
    _cap_rows(trimmed, "findings")
    _cap_rows(trimmed, "recommendations")
    return trimmed


def _trim_category_breakdown(breakdown: dict) -> dict:
    trimmed = dict(breakdown)
    # Already sorted by revenue descending (compute_category_breakdown's
    # own docstring) — a business with many categories still gets the
    # most significant ones first if this ever needs to cap.
    _cap_rows(trimmed, "rows")
    return trimmed


def _trim_report_payload(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return payload
    trimmed = dict(payload)
    if isinstance(trimmed.get("forecast"), dict):
        trimmed["forecast"] = _trim_forecast(trimmed["forecast"])
    if isinstance(trimmed.get("retail_operations"), dict):
        trimmed["retail_operations"] = _trim_retail_operations(trimmed["retail_operations"])
    if isinstance(trimmed.get("findings"), dict):
        trimmed["findings"] = _trim_findings(trimmed["findings"])
    if isinstance(trimmed.get("category_breakdown"), dict):
        trimmed["category_breakdown"] = _trim_category_breakdown(trimmed["category_breakdown"])
    return trimmed


# A plain (non-f-string) template: the ALLOWED_INTENTS/PERIODS/
# METRIC_KEYS parts are baked in once at import time via f-strings
# below (they never change at runtime); {today}/{weekday} are left as
# literal placeholders (escaped {{today}}/{{weekday}} in the f-string
# lines) for _classify_intent to fill in per call via .format() — the
# model can't otherwise resolve a named date ("the 24th of June") to a
# real year without being told what "today" actually is.
_CLASSIFY_SYSTEM_PROMPT_TEMPLATE = (
    "You are an intent classifier for a small business's operations assistant. "
    "Today's date is {today} ({weekday}), in the business's own timezone — use it to resolve any "
    'relative or named date in the question (e.g. "the 24th of June" means the most recent such date '
    "on or before today, unless a year is stated; \"last Tuesday\"/\"yesterday\" resolve the same way).\n"
    "Read the user's question and respond with ONLY a JSON object (no prose, no markdown fences) of the exact "
    'shape {{"intents": [ ... ]}} — a list of 1 to 3 objects, one per distinct question actually being asked. '
    "Almost every question is a single ask — return a one-element list unless the question genuinely contains "
    'more than one distinct request (joined by "and", "also", "as well", "plus", "while you\'re at it", or '
    "phrased as more than one separate question), in which case list one object per distinct request, in the "
    "order asked, capped at 3 (if there are genuinely more than 3, cover only the first 3). "
    "Each object in that list has exactly these keys:\n"
    f'"intent": one of {list(ALLOWED_INTENTS)}\n'
    f'"period": one of {list(ALLOWED_PERIODS)}, or null\n'
    '"start_date": "YYYY-MM-DD", only when period is "explicit_date" — the specific date the question '
    "names, or the start of a named range\n"
    '"end_date": "YYYY-MM-DD", only when period is "explicit_date" and the question names a range wider '
    "than one day — otherwise omit it or repeat start_date\n"
    f'"metric": one of {list(ALLOWED_METRIC_KEYS)} (only when intent is "metric_definition"), or null\n'
    '"search_term": the exact product name/SKU, purchase/PO/order reference, or repair/job/ticket '
    'reference the question names (only when intent is "product_lookup", "purchase_lookup", or '
    '"repair_lookup"), or null\n'
    '"horizon_days": only when intent is "forecast" and the question names a specific timeframe ahead '
    '(e.g. "the next two weeks" -> 14, "next month" -> 30, "the next 10 days" -> 10) — the number of '
    "days that timeframe covers, as an integer. Otherwise null (a plain \"what should I reorder\" with "
    "no named timeframe uses a sensible default).\n\n"
    "What each intent actually contains, so you pick the one with the real data the question needs:\n"
    '- "forecast": projected demand AND a per-product suggested reorder quantity — use this for any '
    '"what/how much should I order/restock/reorder" question, not "findings_recommendations".\n'
    '- "findings_recommendations": flagged issues (low stock, dead stock, thin margin, revenue decline) '
    "with a plain-language recommendation each — no order quantities live here.\n"
    '- "retail_operations": top sellers, stock cover, dead stock, inventory value, sell-through.\n'
    '- "financial_performance": revenue, gross profit/profit, gross margin, top/bottom-margin products, and returns/refunds '
    "(gross vs net revenue, how much was refunded, return rate). Use period \"explicit_date\" for a "
    'question naming a specific day or date range (e.g. "revenue on the 24th of June", "sales last '
    'Tuesday").\n'
    '- "workshop_performance": repairs/workshop revenue and margin, in aggregate (bike-shop businesses '
    'only). Not for one specific repair by reference — that\'s "repair_lookup".\n'
    '- "latest_report": the most recent generated weekly/monthly report.\n'
    '- "product_lookup": detail about ONE specific product by name or SKU — its current stock, cost, or '
    'sell price (e.g. "how much stock of Chain Lube do I have"). Not for "what are my top sellers" or a '
    "stock overview across products — that's \"retail_operations\".\n"
    '- "purchase_history": list-style purchase/order history questions — latest/last/recent orders, recent '
    'purchases, order history, or "most expensive things/items I ordered by unit cost".\n'
    '- "purchase_lookup": detail about a specific purchase, order, or delivery — by PO/purchase '
    'reference, or by product name and/or date (e.g. "what did I order under PO-123", "when did the '
    'chain lube delivery arrive", "what did I order last week"). Set "search_term" to the reference or '
    'product name, and "period"/"start_date"/"end_date" for any date named.\n'
    '- "repair_lookup": detail about one specific repair — by ticket/job/invoice reference, or by date '
    'or a short description (e.g. "how much did repair JOB-364 cost", "what repairs did I do on the '
    '3rd"). Repairs have no stored customer name in this data — a question asking for repairs by a '
    "customer's name can't be answered this way; classify it \"out_of_scope\" rather than guessing.\n"
    '- "category_breakdown": revenue, expenses (money spent buying stock — purchase cost, NOT cost of '
    'goods sold), and stock value, broken down per product category — use this for "what\'s my biggest '
    'cost/expense", "how much did I spend on [category]", "which category makes the most/least money" '
    'questions. Different from "financial_performance": that\'s one whole-business revenue/margin figure '
    'with no cost breakdown to point to; this intent is the one with an actual per-category cost/expense '
    'figure to ground an answer in. Use period "explicit_date" the same way as financial_performance for '
    "a question naming a specific date range.\n\n"
    'Use "metric_definition" when the question asks what a term/metric means, not for one of its numbers. '
    'Use "out_of_scope" for anything not about this business\'s revenue, retail/workshop performance, '
    'forecast, recommendations, reports, or a specific product/purchase/repair — never invent an intent '
    "outside the list above. "
    'Use "default_recent" as the period unless the question clearly asks about last week, last month, or '
    'names a specific date or date range (use "explicit_date" for that last case). '
    "If a previous question/answer in this conversation is shown to you: when the new question is a short "
    'follow-up that only makes sense in light of it (a pronoun, "that", "those", "the previous period", '
    '"and last month?", "why", "what about..."), it is almost always about the SAME topic as the previous '
    "exchange — default to the SAME intent the previous answer was about, adjusting only the period/metric/"
    "search_term the new wording implies, rather than falling back to \"out_of_scope\". For example, if the "
    'previous answer was about revenue and the new question asks "what was the previous period?", classify '
    'it "financial_performance" (its own data already includes both the current and previous-period figures) '
    'rather than treating it as unrelated. If the previous answer gave a branch/shop/location breakdown and '
    'the new question says "merge", "combine", "total", "overall", "together", "full business", or '
    '"whole business", classify it as the same intent as the previous exchange so the combined figure can '
    "be answered from the current data. "
    "Only ignore the previous exchange, and classify on the new "
    "question's own merits, when it clearly stands alone or changes topic."
)


def _today_in_timezone(business_timezone: str, now: datetime) -> date:
    return now.astimezone(ZoneInfo(business_timezone)).date()


def _classify_intent(
    request_repo: AIRequestRepository, *, business_id: uuid.UUID, user_id: str, question: str,
    business_timezone: str, now: datetime,
    previous_question: str | None = None, previous_answer: str | None = None,
) -> list[ClassifyResult]:
    """Returns 1 to _MAX_SUBINTENTS sub-intents, in question order — the
    overwhelming majority of real questions come back as a single-element
    list, same shape today's single-intent behavior always had. See
    _parse_intent_json for how the classify call's "intents" array gets
    validated into this."""
    today = _today_in_timezone(business_timezone, now)
    system_prompt = _CLASSIFY_SYSTEM_PROMPT_TEMPLATE.format(today=today.isoformat(), weekday=today.strftime("%A"))
    messages = [{"role": "system", "content": system_prompt}]
    if previous_question and previous_answer:
        # Last-exchange-only memory, given as real prior turns rather than
        # spliced into the system prompt as text — the standard shape for
        # conversational context with a chat-completions API, and it
        # avoids any prompt-injection-style string-insertion risk.
        # previous_answer is truncated here specifically (not for the
        # explain call below) because this module already hit a real
        # regression once from the classify prompt growing too large for
        # its reasoning-token budget (see this call's own max_tokens
        # comment) — classify only needs enough of the prior answer to
        # tell what was being discussed, not the full text.
        messages.append({"role": "user", "content": previous_question})
        messages.append({"role": "assistant", "content": previous_answer[:_CLASSIFY_PREVIOUS_ANSWER_MAX_CHARS]})
    messages.append({"role": "user", "content": question})
    try:
        # max_tokens=1000 (raised from 700 when the classify JSON shape
        # became a 1-3 item "intents" array instead of one object): the
        # default model is a reasoning model that spends hidden
        # "reasoning" tokens (billed, counted against this budget) before
        # ever emitting the visible JSON — too tight a budget here just
        # silently truncates before real content comes out (content=
        # None), which _parse_intent_json then has no way to tell apart
        # from a genuine "out of scope" verdict. 700 was itself raised
        # from 300 after adding the lookup/explicit-date intents and
        # live-verified against OpenRouter pushing some real questions
        # into consistently burning the full 300-token reasoning budget
        # with zero left for the visible JSON — reproduced
        # deterministically (temperature=0) across repeated calls, not a
        # one-off. A genuine 3-part compound question roughly triples the
        # visible JSON payload on top of that same reasoning-token cost;
        # 1000 is sized to cover that worst case without repeating the
        # same regression — live-verify against a real 3-part question
        # and raise further if truncation shows up again. See
        # app/settings/config.py's openrouter_model comment.
        response = client.chat_completion(
            messages=messages, response_format={"type": "json_object"}, max_tokens=1000, temperature=0.0
        )
    except AIProviderError as exc:
        logger.warning("AI classify call failed business=%s error=%s", business_id, exc)
        _log_request(request_repo, business_id=business_id, user_id=user_id, model="unknown", success=False)
        # Distinct from "out_of_scope": that means the model looked at
        # the question and decided it wasn't about this business's data;
        # this means the provider call itself never completed (network
        # error, rate limit, timeout). Conflating the two used to show
        # "I can't help with that topic" for what was actually "the AI
        # service is down right now" — live-verified this exact
        # confusion after hitting OpenRouter's free-tier daily quota.
        return [ClassifyResult(intent="provider_unavailable")]

    content, tokens_in, tokens_out, model, cost = _extract_message(response)
    _log_request(
        request_repo, business_id=business_id, user_id=user_id, model=model,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_eur=cost, success=content is not None,
    )
    return _parse_intent_json(content, today=today)


def _parse_explicit_dates(raw_start: Any, raw_end: Any, *, today: date) -> tuple[date | None, date | None]:
    """Server-side validation of the classify call's start_date/end_date
    — parsed via date.fromisoformat (never trusted as-is), end_date
    defaults to start_date rather than rejecting the whole range over
    one bad field, start<=end enforced, and both bounded to a sane
    window around today so a malformed/hallucinated date (e.g. year
    1900 or 3000) can't slip through. Returns (None, None) on any
    failure — the caller falls back to "default_recent", exactly like
    an unparseable period does today."""
    if not isinstance(raw_start, str):
        return None, None
    try:
        start_date = date.fromisoformat(raw_start)
    except ValueError:
        return None, None

    end_date = start_date
    if isinstance(raw_end, str):
        try:
            end_date = date.fromisoformat(raw_end)
        except ValueError:
            end_date = start_date

    if start_date > end_date:
        return None, None

    floor = today - timedelta(days=365 * _MAX_EXPLICIT_DATE_YEARS_BACK)
    ceiling = today + timedelta(days=365 * _MAX_EXPLICIT_DATE_YEARS_FORWARD)
    if start_date < floor or end_date > ceiling:
        return None, None

    return start_date, end_date


def _parse_one_intent(data: dict, *, today: date) -> ClassifyResult:
    """Server-side validation for a single sub-intent object — every
    field validated exactly as a lone-object classify response always
    was. See _parse_intent_json for the outer list-level parsing (the
    "intents" array, capping, and fallback shapes) this feeds into."""
    intent = data.get("intent")
    if intent not in ALLOWED_INTENTS:
        if intent is not None:
            # Present but not a recognised value — likely a hallucinated
            # intent name, distinct from the model simply omitting the
            # field (already covered by data.get returning None above).
            logger.warning("Classify call returned an unrecognised intent %r, defaulting to out_of_scope", intent)
        intent = "out_of_scope"

    period = data.get("period")
    if period not in ALLOWED_PERIODS:
        period = "default_recent"

    start_date = end_date = None
    if period == "explicit_date":
        start_date, end_date = _parse_explicit_dates(data.get("start_date"), data.get("end_date"), today=today)
        if start_date is None:
            period = "default_recent"  # half-valid/unparseable range — fail closed, don't guess

    metric = data.get("metric")
    if metric not in ALLOWED_METRIC_KEYS:
        metric = None

    search_term = data.get("search_term")
    if not isinstance(search_term, str) or not search_term.strip():
        search_term = None
    else:
        search_term = search_term.strip()[:_MAX_SEARCH_TERM_LENGTH]

    horizon_days = _parse_horizon_days(data.get("horizon_days"))

    return ClassifyResult(
        intent=intent, period=period, start_date=start_date, end_date=end_date, metric=metric,
        search_term=search_term, horizon_days=horizon_days,
    )


def _parse_intent_json(content: str | None, *, today: date) -> list[ClassifyResult]:
    """`content is None`, a JSON-decode failure, or a non-dict payload all
    fall back to a single out_of_scope result — but unlike a model
    genuinely deciding a question is out of scope (a normal, silent
    outcome), each of these means something went wrong upstream (the
    model didn't respect response_format, ran out of its token budget
    before emitting visible content, ...), so each is logged. Found live:
    this silence made a real regression (a newly added fallback model
    returning unparseable content) look identical to ordinary "not about
    this business" refusals for every single question, with zero trace
    in the logs to tell the two apart — this is the fix for that blind
    spot.

    Reads `data["intents"]` as a list of 1-_MAX_SUBINTENTS sub-intent
    objects (see _CLASSIFY_SYSTEM_PROMPT_TEMPLATE's own instruction for
    this shape), each validated independently via _parse_one_intent.
    Falls back to treating a bare, non-array-wrapped object (one with an
    "intent" key directly) as a single-element list — defensive, since a
    free-tier model has a documented history of not always following the
    exact JSON shape asked for (see _classify_intent's own max_tokens
    comment)."""
    if content is None:
        logger.warning("Classify call returned no content — provider likely exhausted its token budget")
        return [ClassifyResult(intent="out_of_scope")]
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Classify call returned non-JSON content, defaulting to out_of_scope: %r", content[:500])
        return [ClassifyResult(intent="out_of_scope")]
    if not isinstance(data, dict):
        logger.warning("Classify call returned JSON that wasn't an object, defaulting to out_of_scope: %r", content[:500])
        return [ClassifyResult(intent="out_of_scope")]

    raw_intents = data.get("intents")
    if not isinstance(raw_intents, list) or not raw_intents:
        if isinstance(data.get("intent"), str):
            raw_intents = [data]
        else:
            logger.warning(
                'Classify call returned no usable "intents" list, defaulting to out_of_scope: %r', content[:500]
            )
            return [ClassifyResult(intent="out_of_scope")]

    parsed = [_parse_one_intent(item, today=today) for item in raw_intents[:_MAX_SUBINTENTS] if isinstance(item, dict)]
    if not parsed:
        logger.warning(
            'Classify call\'s "intents" list had no usable objects, defaulting to out_of_scope: %r', content[:500]
        )
        return [ClassifyResult(intent="out_of_scope")]
    return parsed


def _parse_horizon_days(raw: Any) -> int | None:
    """Server-side validation, same fail-closed pattern as
    _parse_explicit_dates: never trust the model's number as-is. A
    non-integer (a bool is deliberately rejected too — Python's bool is
    an int subclass), or one outside the same [1, 90] bound the API
    route itself enforces, falls back to None (the caller's own default
    of 7), not a clamped/guessed value — a malformed number here isn't
    worth silently reinterpreting."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    if raw < _MIN_HORIZON_DAYS or raw > _MAX_HORIZON_DAYS:
        return None
    return raw


# Loaded once at import time, not read per-request — these two files are
# the actual governance artifacts (Layer 1/Layer 4 of the ORLA AI Skills,
# SOPs, Grounding & Personality plan): orla_constitution.md is the
# immutable, versioned set of grounding/scope rules every explain-step
# answer must follow (previously an inline f-string here, now a
# reviewable, diffable file of its own); orla_personality.md is the tone
# layer, explicitly subordinate to the constitution — it can change how
# an answer sounds, never what it says. Deliberately NOT applied to the
# classify step's prompt: that step is a pure structured-output/JSON
# task, and this codebase already hit real trouble once (see
# _classify_intent's own max_tokens comment) from a classify prompt
# growing large enough to burn its whole reasoning-token budget before
# emitting the JSON — adding a second large block of prose there risks
# the same regression for close to no benefit (there is no free-text
# "voice" for classify's JSON output to carry).
_AI_MODULE_DIR = Path(__file__).parent
_ORLA_CONSTITUTION = (_AI_MODULE_DIR / "orla_constitution.md").read_text(encoding="utf-8")
_ORLA_PERSONALITY = (_AI_MODULE_DIR / "orla_personality.md").read_text(encoding="utf-8")

# Plain concatenation, not str.format() — orla_constitution.md/orla_
# personality.md are free-form prose that may contain a literal "{" or
# "}" (e.g. quoting a field name), which .format() would misread as a
# placeholder and raise on. context_json is appended directly in
# _generate_answer instead, with no format-string parsing involved.
_EXPLAIN_SYSTEM_PROMPT_PREFIX = f"{_ORLA_CONSTITUTION}\n\n{_ORLA_PERSONALITY}\n\nDATA:\n"


# Only appended when answer_question is assembling a genuine multi-intent
# question (several different intents, each with its own "part_N" key in
# the supplied DATA) — not the same thing as a single intent's answer
# covering several list items ("give me 5 actions"), which _generate_
# answer already handled before this existed and still does the same way.
_MULTI_PART_INSTRUCTION = (
    "This question has multiple distinct parts, numbered part_1, part_2, ... in the DATA below (there may also "
    "be an _already_answered list of parts that already have their own final answer — do not re-answer those, "
    "they're shown only so you have their figures for context if the question refers back to them). Answer every "
    "part_N key present in DATA, briefly, in ascending numeric order. Start each part's own answer on its own "
    "line with the exact marker ⟦PART_n⟧ (matching that part's own number, e.g. ⟦PART_1⟧), "
    "with nothing else on that line — no other text before or after the marker on that line. If a part's \"data\" "
    "field is null, say so plainly in one short sentence for that part rather than guessing. Never invent an "
    "extra part or marker beyond the part_N keys actually present in DATA.\n\n"
)


def _generate_answer(
    request_repo: AIRequestRepository, *, business_id: uuid.UUID, user_id: str, question: str, context: dict,
    scope_label: str, previous_question: str | None = None, previous_answer: str | None = None,
    multi_part: bool = False,
) -> str | None:
    # Explicit, stated outright rather than left for the model to infer —
    # live-reproduced bug: without this, a branch-scoped or combined-
    # branches context (app/application/business_group.py) reads to the
    # model as unlabelled generic figures, and a question naming the
    # scope by name ("revenue in Galway?") gets answered "I don't have a
    # location breakdown" even though the JSON below *is* that exact
    # breakdown already.
    scope_note = (
        f"(This data is already scoped to: {scope_label} — it is not a whole-account total unless stated. "
        "If a `branches` list is present in the supplied data, use it for branch/shop/location breakdowns; "
        "otherwise do not claim to have a further per-branch/location breakdown.)\n"
    )
    multi_part_note = _MULTI_PART_INSTRUCTION if multi_part else ""
    system_prompt = _EXPLAIN_SYSTEM_PROMPT_PREFIX + scope_note + multi_part_note + json.dumps(context, default=str)
    messages = [{"role": "system", "content": system_prompt}]
    if previous_question and previous_answer:
        # Same last-exchange-only shape as _classify_intent above, given
        # as real prior turns — full previous_answer here, not truncated,
        # since the explain call already has a larger token budget and
        # this is exactly where natural conversational recall matters
        # (e.g. correctly restating a figure it already gave).
        messages.append({"role": "user", "content": previous_question})
        messages.append({"role": "assistant", "content": previous_answer})
    messages.append({"role": "user", "content": question})
    try:
        # Same reasoning-token headroom rationale as _classify_intent
        # above; raised from 500 after a live fire-test run showed a
        # single intent's answer covering several distinct list items
        # ("give me 5 actions, cite the data, flag uncertainty for each")
        # visibly truncating mid-word — 500 was enough for the usual 2-4-
        # sentence answer but not for a question that explicitly asks the
        # prompt above to cover several distinct items. multi_part raises
        # this further still (800 -> 1600): a genuine multi-intent answer
        # is proportionally longer again (up to _MAX_SUBINTENTS separate
        # answers plus their markers). Live-verified against real
        # 2-part and 3-part questions on the real dev stack (Test Bike
        # Shop, real OpenRouter) at 1200: both came back correctly
        # formed, but tokens_out landed at 1191 and 1198 — within single
        # digits of truncating outright, not a comfortable margin. Raised
        # to 1600 for real headroom rather than leaving it at a value one
        # slightly longer answer away from silently cutting a part off
        # mid-word.
        response = client.chat_completion(
            messages=messages, max_tokens=1600 if multi_part else 800, temperature=0.2
        )
    except AIProviderError as exc:
        logger.warning("AI explain call failed business=%s error=%s", business_id, exc)
        _log_request(request_repo, business_id=business_id, user_id=user_id, model="unknown", success=False)
        return None

    content, tokens_in, tokens_out, model, cost = _extract_message(response)
    _log_request(
        request_repo, business_id=business_id, user_id=user_id, model=model,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_eur=cost, success=content is not None,
    )
    return content


def _extract_message(response: dict) -> tuple[str | None, int, int, str, Decimal]:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = None
    usage = response.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens") or 0)
    tokens_out = int(usage.get("completion_tokens") or 0)
    # OpenRouter reports this in USD, not EUR — stored as-is (see
    # app/ai/client.py's usage.include comment); a stated approximation,
    # not a real currency conversion.
    raw_cost = usage.get("cost")
    cost = Decimal(str(raw_cost)) if raw_cost is not None else Decimal("0")
    model = response.get("model") or "unknown"
    return content, tokens_in, tokens_out, model, cost


def _log_request(
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
        business_id=business_id, user_id=user_id, lane=_LANE, provider=_PROVIDER, model=model,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_eur=cost_eur, success=success,
    )
