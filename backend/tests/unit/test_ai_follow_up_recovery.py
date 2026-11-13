"""ORLA-91 eval findings in follow-up handling — pure functions."""

from datetime import date

from app.ai.service import (
    ClassifyResult,
    _follow_up_period,
    _looks_like_short_follow_up,
    _parse_intent_json,
    _recover_out_of_scope_intent,
    _recover_reorder_follow_up,
)

_TODAY = date(2026, 11, 13)


def test_short_continuation_recovers_the_previous_topic():
    assert _recover_out_of_scope_intent("And the month before?", "financial_performance") == "financial_performance"
    assert _recover_out_of_scope_intent("What about last week?", "workshop_performance") == "workshop_performance"


def test_short_continuation_without_a_continuable_topic_stays_refused():
    assert _recover_out_of_scope_intent("And the month before?", None) is None
    assert _recover_out_of_scope_intent("And the month before?", "product_lookup") is None


def test_long_or_unrelated_questions_are_not_short_follow_ups():
    assert not _looks_like_short_follow_up("What is the capital of France?")
    assert not _looks_like_short_follow_up("And can you also write me a long poem about bicycles and the sea please?")


def test_follow_up_period_reads_month_or_week_from_the_wording():
    assert _follow_up_period("And the month before?", "default_recent") == "last_completed_month"
    assert _follow_up_period("And the week before?", "default_recent") == "last_completed_week"
    assert _follow_up_period("And the month before?", "explicit_date") == "explicit_date"
    assert _follow_up_period("And overall?", "default_recent") == "default_recent"


def test_urgency_question_after_a_reorder_answer_stays_on_the_forecast():
    lookup = ClassifyResult(intent="product_lookup", search_term="Trailblazer MTB 29")
    recovered = _recover_reorder_follow_up(lookup, "Which one of those is the most urgent?", "forecast", ())
    assert recovered.intent == "forecast"
    # Also when the reorder part was one part of a multi-part previous answer.
    multi = _recover_reorder_follow_up(
        lookup, "Which of those first?", "financial_performance", ("financial_performance", "forecast")
    )
    assert multi.intent == "forecast"


def test_urgency_recovery_needs_a_reorder_previous_turn_and_a_back_reference():
    lookup = ClassifyResult(intent="product_lookup", search_term="Trailblazer MTB 29")
    assert _recover_reorder_follow_up(lookup, "Which one of those is the most urgent?", "financial_performance", ()) is lookup
    assert _recover_reorder_follow_up(lookup, "Is the Trailblazer MTB 29 urgent?", "forecast", ()) is lookup
    unavailable = ClassifyResult(intent="provider_unavailable")
    assert _recover_reorder_follow_up(unavailable, "Which of those is most urgent?", "forecast", ()) is unavailable


def test_unpadded_explicit_dates_parse():
    content = (
        '{"intents": [{"intent": "financial_performance", "period": "explicit_date", '
        '"start_date": "2026-11-1", "end_date": "2026-11-7"}]}'
    )
    [result] = _parse_intent_json(content, today=_TODAY)
    assert (result.period, result.start_date, result.end_date) == ("explicit_date", date(2026, 11, 1), date(2026, 11, 7))


def test_impossible_dates_still_fail_closed():
    content = '{"intents": [{"intent": "financial_performance", "period": "explicit_date", "start_date": "2026-13-40"}]}'
    [result] = _parse_intent_json(content, today=_TODAY)
    assert (result.period, result.start_date) == ("default_recent", None)


def test_previous_period_follow_up_keeps_the_previous_questions_period():
    from app.ai.service import _keep_previous_period

    month = ClassifyResult(intent="workshop_performance", period="last_completed_month")
    kept = _keep_previous_period(month, "What was it in the previous period?", "How is the workshop doing?")
    assert kept.period == "default_recent"
    week = _keep_previous_period(
        ClassifyResult(intent="financial_performance"), "And the previous period?", "What was revenue last week?"
    )
    assert week.period == "last_completed_week"


def test_previous_period_follow_up_leaves_named_dates_and_other_questions_alone():
    from app.ai.service import _keep_previous_period

    explicit = ClassifyResult(intent="financial_performance", period="explicit_date", start_date=date(2026, 10, 24))
    assert _keep_previous_period(explicit, "And the previous period?", "Revenue on 24 October?") is explicit
    month = ClassifyResult(intent="financial_performance", period="last_completed_month")
    assert _keep_previous_period(month, "What about last month?", "How is revenue?") is month
    assert _keep_previous_period(month, "What was the previous period?", None) is month


def test_completed_week_or_month_needs_a_week_or_month_in_the_question():
    from app.ai.service import _drop_unasked_fixed_period

    month = ClassifyResult(intent="financial_performance", period="last_completed_month")
    dropped = _drop_unasked_fixed_period(month, "Is revenue up or down compared with the previous period?", None)
    assert dropped.period == "default_recent"
    assert _drop_unasked_fixed_period(month, "What was my revenue last month?", None) is month
    assert _drop_unasked_fixed_period(month, "And the one before?", "What was revenue last month?") is month
    explicit = ClassifyResult(intent="financial_performance", period="explicit_date", start_date=date(2026, 10, 1))
    assert _drop_unasked_fixed_period(explicit, "Revenue on 1 October?", None) is explicit


def test_month_name_counts_as_asking_for_a_month():
    from app.ai.service import _drop_unasked_fixed_period

    month = ClassifyResult(intent="category_breakdown", period="last_completed_month")
    asked = "Which category did I spend the most on in October 2026?"
    assert _drop_unasked_fixed_period(month, asked, None) is month


def test_classify_prompt_lists_the_last_seven_days_with_weekdays():
    from app.ai.service import _recent_days_text

    text = _recent_days_text(date(2026, 11, 13))
    assert text.startswith("Thursday 2026-11-12, Wednesday 2026-11-11, Tuesday 2026-11-10")
    assert text.endswith("Friday 2026-11-06")
