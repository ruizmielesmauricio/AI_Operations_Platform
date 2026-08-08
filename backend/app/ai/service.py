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
    "repair_lookup",
    "category_breakdown",
    "out_of_scope",
)
# explicit_date added alongside the lookup intents — a question naming a
# specific date/range ("revenue on the 24th of June") previously had no
# period value that could represent it at all.
ALLOWED_PERIODS = ("default_recent", "last_completed_week", "last_completed_month", "explicit_date")
_MAX_SEARCH_TERM_LENGTH = 200
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
    intent: str
    grounded: bool
    # A fixed, small set of app pages the answer references — always
    # {"dashboard", "reports"} or empty, never arbitrary text/URLs from
    # the model. The frontend renders these as real, safe <a> elements
    # itself (app/chat/page.tsx) rather than ever treating any part of
    # `answer` (which may include model-generated text) as HTML.
    links: tuple[str, ...] = ()


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
    if named_business is not None:
        business = named_business
    elif all_branches:
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

    classify = _classify_intent(
        request_repo, business_id=business_id, user_id=user_id, question=question,
        business_timezone=business.timezone, now=resolved_now,
        previous_question=previous_question, previous_answer=previous_answer,
    )
    intent = classify.intent

    if intent == "provider_unavailable":
        return AnswerResult(answer=_UNAVAILABLE_MESSAGE, intent="provider_unavailable", grounded=False)

    if intent == "metric_definition":
        definition = get_definition(classify.metric) if classify.metric else None
        if definition is None:
            return AnswerResult(answer=_SAFE_FALLBACK, intent="out_of_scope", grounded=True)
        return AnswerResult(answer=definition, intent="metric_definition", grounded=True)

    if intent == "out_of_scope":
        # Defense in depth against classify unreliability (free-tier
        # model variance) — live fire-test evidence: a reorder/stock-out-
        # shaped question ("what's going to run out of stock", "what
        # should I spend €2,000 on restocking") occasionally came back
        # out_of_scope even though the classify prompt's own "forecast"
        # description explicitly covers this exact question shape. Only
        # ever promotes out_of_scope -> forecast, using the same
        # deterministic keyword check already built for the priority-
        # list feature — can never grant a more sensitive intent or
        # override a genuine out-of-scope verdict for anything else, so
        # this only recovers real questions, never weakens the refusal
        # path itself.
        if _looks_like_a_reorder_question(question):
            classify = ClassifyResult(
                intent="forecast", period=classify.period, start_date=classify.start_date, end_date=classify.end_date
            )
            intent = "forecast"
        elif _looks_like_a_period_follow_up_question(question) and previous_intent in _CONTINUABLE_INTENTS:
            # Second, narrower recovery net, same shape as the reorder
            # one above: a "what/when was the previous/last period?"
            # follow-up only makes sense in light of whatever was just
            # discussed — recover to that exact intent (validated against
            # the fixed _CONTINUABLE_INTENTS allow-list, never trusted as
            # client input past that membership check) rather than
            # guessing a default. No previous_intent, or one outside the
            # allow-list (a lookup intent, or another out_of_scope/
            # provider_unavailable/metric_definition turn) -> falls
            # through to the same safe refusal as any other unresolved
            # out_of_scope, never guessed.
            classify = ClassifyResult(
                intent=previous_intent, period=classify.period, start_date=classify.start_date,
                end_date=classify.end_date,
            )
            intent = previous_intent
        else:
            return AnswerResult(answer=_SAFE_FALLBACK, intent="out_of_scope", grounded=True)

    if intent in ("product_lookup", "purchase_lookup", "repair_lookup"):
        context, early_result = _dispatch_lookup(db, business=business, intent=intent, classify=classify)
        if early_result is not None:
            return early_result
    else:
        context = _fetch_context(
            db, business=business, intent=intent, classify=classify, now=resolved_now,
            combined_businesses=combined_businesses,
        )
        if context is None:
            # Not applicable (e.g. workshop performance for a non-bike-shop
            # template, or no report exists yet) — same safe fallback, zero
            # further AI cost.
            return AnswerResult(answer=_SAFE_FALLBACK, intent="out_of_scope", grounded=True)

    # Set aside for the deterministic priority-list builder below, then
    # stripped before the LLM ever sees this dict — the *complete*
    # reorder list costs nothing extra (it's local formatting, not
    # another AI call), so it doesn't need the same cost-driven cap as
    # what actually goes in the prompt (see _MAX_CONTEXT_ROWS).
    all_forecast_products = context.pop("_all_products_for_priority_list", None)

    answer_text = _generate_answer(
        request_repo, business_id=business_id, user_id=user_id, question=question, context=context,
        previous_question=previous_question, previous_answer=previous_answer,
    )
    if answer_text is None:
        # Tagged "provider_unavailable", not the already-classified
        # intent — same reasoning as the classify-step failure above:
        # this means the provider call itself never completed (network/
        # rate-limit/timeout) at the *explain* step, not that whatever
        # was classified genuinely failed to produce an answer. Found
        # live via a fire-test run: this branch was silently keeping the
        # original intent, which is misleading for anything inspecting
        # `result.intent` (logging, analytics) even though the message
        # shown to the user was already correct.
        return AnswerResult(answer=_UNAVAILABLE_MESSAGE, intent="provider_unavailable", grounded=False)

    result = validate_grounded(answer_text, context, question=question, previous_answer=previous_answer)
    if not result.grounded:
        logger.warning(
            "Ungrounded AI answer rejected business=%s intent=%s unsupported=%s",
            business_id, intent, result.unsupported_claims,
        )
        return AnswerResult(answer=_UNGROUNDED_FALLBACK, intent=intent, grounded=False)

    final_answer = answer_text
    if intent == "forecast" and _looks_like_a_reorder_question(question) and all_forecast_products:
        built = _build_priority_order_list(all_forecast_products)
        if built is not None:
            priority_list, list_itself_truncated = built
            final_answer = f"{final_answer}\n\n{priority_list}"
            if not list_itself_truncated:
                # The priority list above already answers "what do I need
                # to order" completely (it's built from the untrimmed
                # product list, not the LLM's capped view) — the generic
                # "only 15 of 152 shown, check elsewhere" note would be
                # confusing noise right next to an answer that isn't
                # partial. If the priority list itself had to truncate
                # (more than _MAX_PRIORITY_LIST_DISPLAY products need
                # reordering), the note and links stay — genuinely still
                # a partial answer.
                context.pop("products_shown_of_total", None)

    final_answer = _append_truncation_disclosure(final_answer, context)
    links = ("dashboard", "reports") if _find_shown_of_total_notes(context) else ()
    return AnswerResult(answer=final_answer, intent=intent, grounded=True, links=links)


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


def _looks_like_a_reorder_question(question: str) -> bool:
    """A cheap, deterministic check gating the priority-list build below
    — the `forecast` intent's context also covers plain revenue-forecast
    questions ("what's next week looking like?"), which shouldn't get an
    unrelated product-reorder list appended."""
    lowered = question.lower()
    return any(keyword in lowered for keyword in _REORDER_KEYWORDS)


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


# Zero-cost — this is local formatting after the AI calls are already
# done, not another prompt — so it can afford to be far more generous
# than _MAX_CONTEXT_ROWS (which bounds what's actually sent to the
# model). Still bounded, because a 100-line chat message is bad UX
# regardless of cost.
_MAX_PRIORITY_LIST_DISPLAY = 30


def _build_priority_order_list(all_products: list) -> tuple[str, bool] | None:
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

    lines = []
    for i, product in enumerate(to_order[:_MAX_PRIORITY_LIST_DISPLAY], start=1):
        name = product.get("name", "Unknown product")
        quantity = product.get("suggested_reorder_quantity")
        cover = product.get("days_of_cover_at_forecast_rate")
        cover_note = f" ({cover} days cover left)" if cover is not None else ""
        lines.append(f"{i}. {name} — {quantity} units{cover_note}")

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


def _dispatch_lookup(
    db: Session, *, business: Business, intent: str, classify: ClassifyResult
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

    if not result.matches:
        term = classify.search_term or "that"
        message = f'I couldn\'t find anything matching "{term}" in your data.'
        return None, AnswerResult(answer=message, intent=intent, grounded=True)

    if len(result.matches) > 1:
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
    "Read the user's question and respond with ONLY a JSON object (no prose, no markdown fences) "
    "with exactly these keys:\n"
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
    '- "financial_performance": revenue, gross margin, top/bottom-margin products, and returns/refunds '
    "(gross vs net revenue, how much was refunded, return rate). Use period \"explicit_date\" for a "
    'question naming a specific day or date range (e.g. "revenue on the 24th of June", "sales last '
    'Tuesday").\n'
    '- "workshop_performance": repairs/workshop revenue and margin, in aggregate (bike-shop businesses '
    'only). Not for one specific repair by reference — that\'s "repair_lookup".\n'
    '- "latest_report": the most recent generated weekly/monthly report.\n'
    '- "product_lookup": detail about ONE specific product by name or SKU — its current stock, cost, or '
    'sell price (e.g. "how much stock of Chain Lube do I have"). Not for "what are my top sellers" or a '
    "stock overview across products — that's \"retail_operations\".\n"
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
    "rather than treating it as unrelated. Only ignore the previous exchange, and classify on the new "
    "question's own merits, when it clearly stands alone or changes topic."
)


def _today_in_timezone(business_timezone: str, now: datetime) -> date:
    return now.astimezone(ZoneInfo(business_timezone)).date()


def _classify_intent(
    request_repo: AIRequestRepository, *, business_id: uuid.UUID, user_id: str, question: str,
    business_timezone: str, now: datetime,
    previous_question: str | None = None, previous_answer: str | None = None,
) -> ClassifyResult:
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
        # max_tokens=700, not the ~20-50 a plain classification would
        # need: the default model is a reasoning model that spends
        # hidden "reasoning" tokens (billed, counted against this
        # budget) before ever emitting the visible JSON — too tight a
        # budget here just silently truncates before real content comes
        # out (content=None), which _parse_intent_json then has no way
        # to tell apart from a genuine "out of scope" verdict. Raised
        # from 300 after adding the lookup/explicit-date intents: this
        # module's classify prompt grew substantially (10 intents, date
        # extraction, search-term extraction), and live-verified against
        # OpenRouter this pushed some real questions into consistently
        # burning the full 300-token reasoning budget with zero left for
        # the visible JSON — reproduced deterministically (temperature=0)
        # across repeated calls, not a one-off. See
        # app/settings/config.py's openrouter_model comment.
        response = client.chat_completion(
            messages=messages, response_format={"type": "json_object"}, max_tokens=700, temperature=0.0
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
        return ClassifyResult(intent="provider_unavailable")

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


def _parse_intent_json(content: str | None, *, today: date) -> ClassifyResult:
    """`content is None`, a JSON-decode failure, or a non-dict payload
    all fall back to "out_of_scope" — but unlike a model genuinely
    deciding a question is out of scope (a normal, silent outcome), each
    of these means something went wrong upstream (the model didn't
    respect response_format, ran out of its token budget before emitting
    visible content, ...), so each is logged. Found live: this silence
    made a real regression (a newly added fallback model returning
    unparseable content) look identical to ordinary "not about this
    business" refusals for every single question, with zero trace in the
    logs to tell the two apart — this is the fix for that blind spot."""
    if content is None:
        logger.warning("Classify call returned no content — provider likely exhausted its token budget")
        return ClassifyResult(intent="out_of_scope")
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Classify call returned non-JSON content, defaulting to out_of_scope: %r", content[:500])
        return ClassifyResult(intent="out_of_scope")
    if not isinstance(data, dict):
        logger.warning("Classify call returned JSON that wasn't an object, defaulting to out_of_scope: %r", content[:500])
        return ClassifyResult(intent="out_of_scope")

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


def _generate_answer(
    request_repo: AIRequestRepository, *, business_id: uuid.UUID, user_id: str, question: str, context: dict,
    previous_question: str | None = None, previous_answer: str | None = None,
) -> str | None:
    system_prompt = _EXPLAIN_SYSTEM_PROMPT_PREFIX + json.dumps(context, default=str)
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
        # genuinely multi-part question ("give me 5 actions, cite the
        # data, flag uncertainty for each") visibly truncating mid-word
        # — 500 was enough for the usual 2-4-sentence answer but not for
        # a question that explicitly asks the prompt above to cover
        # several distinct items.
        response = client.chat_completion(messages=messages, max_tokens=800, temperature=0.2)
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
