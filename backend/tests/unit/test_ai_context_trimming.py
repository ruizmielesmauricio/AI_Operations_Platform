from app.ai.service import (
    _CONTINUABLE_INTENTS,
    _MAX_CONTEXT_ROWS,
    _MAX_PRIORITY_LIST_DISPLAY,
    _append_truncation_disclosure,
    _build_priority_order_list,
    _looks_like_a_period_follow_up_question,
    _looks_like_a_reorder_question,
    _trim_findings,
    _trim_forecast,
    _trim_retail_operations,
)


def _forecast_product(i):
    return {
        "product_id": str(i),
        "name": f"Product {i}",
        "result": {"daily": [{"forecast_date": "2026-01-01", "point": "1", "low": "0", "high": "2"}], "total_point": "10"},
        "current_stock": 5,
        "suggested_reorder_quantity": 3,
        "days_of_cover_at_forecast_rate": "2",
    }


def test_trim_forecast_caps_products_and_drops_daily_curves():
    forecast = {
        "horizon_days": 7,
        "revenue": {"horizon_days": 7, "result": {"daily": [{"a": 1}], "total_point": "100"}},
        "products": [_forecast_product(i) for i in range(50)],
        "products_excluded_insufficient_data": 0,
    }
    trimmed = _trim_forecast(forecast)
    assert len(trimmed["products"]) == _MAX_CONTEXT_ROWS
    assert "daily" not in trimmed["revenue"]["result"]
    assert all("daily" not in p["result"] for p in trimmed["products"])
    # Non-chart fields survive untouched.
    assert trimmed["products"][0]["suggested_reorder_quantity"] == 3
    assert trimmed["revenue"]["result"]["total_point"] == "100"
    # A truncated list gets a disclosure note the model can honestly
    # repeat (and the guardrail will accept, since both numbers are now
    # literally present in the context).
    assert trimmed["products_shown_of_total"] == "15 of 50"


def test_trim_forecast_adds_no_disclosure_note_when_nothing_was_cut():
    forecast = {"products": [_forecast_product(i) for i in range(5)]}
    trimmed = _trim_forecast(forecast)
    assert len(trimmed["products"]) == 5
    assert "products_shown_of_total" not in trimmed


def test_trim_retail_operations_caps_stock_cover_and_dead_stock():
    retail = {
        "stock_cover": [{"product_id": str(i)} for i in range(50)],
        "dead_stock": [{"product_id": str(i)} for i in range(50)],
        "top_sellers_by_units": [{"product_id": "1"}],
    }
    trimmed = _trim_retail_operations(retail)
    assert len(trimmed["stock_cover"]) == _MAX_CONTEXT_ROWS
    assert len(trimmed["dead_stock"]) == _MAX_CONTEXT_ROWS
    assert trimmed["stock_cover_shown_of_total"] == "15 of 50"
    assert trimmed["dead_stock_shown_of_total"] == "15 of 50"
    assert trimmed["top_sellers_by_units"] == [{"product_id": "1"}]  # already small, untouched


def test_trim_findings_caps_both_lists():
    findings = {
        "findings": [{"type": "low_stock"} for _ in range(50)],
        "recommendations": [{"title": "x"} for _ in range(50)],
    }
    trimmed = _trim_findings(findings)
    assert len(trimmed["findings"]) == _MAX_CONTEXT_ROWS
    assert len(trimmed["recommendations"]) == _MAX_CONTEXT_ROWS
    assert trimmed["findings_shown_of_total"] == "15 of 50"
    assert trimmed["recommendations_shown_of_total"] == "15 of 50"


def test_append_truncation_disclosure_is_a_noop_when_nothing_was_capped():
    context = {"products": [{"name": "x"}]}
    answer = "Everything looks fine."
    assert _append_truncation_disclosure(answer, context) == answer


def test_append_truncation_disclosure_always_appends_regardless_of_what_the_model_said():
    # Deterministic, not a prompt hope — live-verified the model itself
    # doesn't reliably mention the cap even when explicitly asked for
    # "the full list," so this must not depend on the model's answer
    # text at all.
    context = {"products_shown_of_total": "15 of 152"}
    answer = "You should reorder these four products."
    result = _append_truncation_disclosure(answer, context)
    assert result.startswith(answer)
    assert "15 of 152" in result
    assert "Dashboard or Reports page" in result


def test_append_truncation_disclosure_finds_notes_nested_inside_a_stored_report():
    context = {"forecast": {"products_shown_of_total": "15 of 152"}, "findings": {"findings_shown_of_total": "15 of 65"}}
    result = _append_truncation_disclosure("Answer.", context)
    assert "15 of 152" in result
    assert "15 of 65" in result


def test_looks_like_a_reorder_question_matches_expected_phrasings():
    assert _looks_like_a_reorder_question("What should I order this week?") is True
    assert _looks_like_a_reorder_question("Do I need to restock anything?") is True
    assert _looks_like_a_reorder_question("How is my revenue doing?") is False


def test_looks_like_a_reorder_question_matches_run_out_of_stock_phrasings():
    # Added after a live fire-test run found "run out of stock"-shaped
    # questions occasionally misclassified as out_of_scope — these
    # keywords back answer_question's out_of_scope -> forecast recovery.
    assert _looks_like_a_reorder_question("What is likely to run out of stock during the next two weeks?") is True
    assert _looks_like_a_reorder_question("Which products are at risk of a stock out?") is True
    assert _looks_like_a_reorder_question("Is anything close to a stockout?") is True


def test_looks_like_a_period_follow_up_question_matches_the_three_live_reported_phrasings():
    # Three separate real transcripts, three different phrasings, all
    # classified out_of_scope despite an obvious prior exchange to
    # resolve against — these keywords back answer_question's
    # out_of_scope -> previous_intent recovery.
    assert _looks_like_a_period_follow_up_question("What was the previous period?") is True
    assert _looks_like_a_period_follow_up_question("When was the previous period?") is True
    assert _looks_like_a_period_follow_up_question("What is the last period?") is True


def test_looks_like_a_period_follow_up_question_does_not_match_an_unrelated_question():
    assert _looks_like_a_period_follow_up_question("How's my revenue doing?") is False
    assert _looks_like_a_period_follow_up_question("What's the weather like today?") is False


def test_continuable_intents_excludes_lookup_and_zero_cost_intents():
    # The allow-list a recovered previous_intent must be a member of —
    # lookup intents have their own disambiguation flow and shouldn't be
    # blindly continued; metric_definition/out_of_scope/
    # provider_unavailable/usage_limit_reached aren't real data topics.
    assert "financial_performance" in _CONTINUABLE_INTENTS
    assert "product_lookup" not in _CONTINUABLE_INTENTS
    assert "purchase_lookup" not in _CONTINUABLE_INTENTS
    assert "repair_lookup" not in _CONTINUABLE_INTENTS
    assert "metric_definition" not in _CONTINUABLE_INTENTS
    assert "out_of_scope" not in _CONTINUABLE_INTENTS
    assert "provider_unavailable" not in _CONTINUABLE_INTENTS


def test_build_priority_order_list_orders_by_the_input_order_and_skips_zero_quantity():
    # Urgency ordering is the caller's responsibility (get_forecast
    # already sorts soonest-out-of-stock-first) — this just must not
    # re-sort or reorder what it's given, and must skip anything with no
    # actual reorder need.
    products = [
        {"name": "Urgent Item", "suggested_reorder_quantity": 10, "days_of_cover_at_forecast_rate": "0"},
        {"name": "No Reorder Needed", "suggested_reorder_quantity": 0, "days_of_cover_at_forecast_rate": "40"},
        {"name": "Less Urgent Item", "suggested_reorder_quantity": 2, "days_of_cover_at_forecast_rate": "12"},
    ]
    built = _build_priority_order_list(products)
    assert built is not None
    text, truncated = built
    assert truncated is False
    assert text.index("Urgent Item") < text.index("Less Urgent Item")
    assert "No Reorder Needed" not in text
    assert text.startswith("Priority order (most urgent first):")


def test_build_priority_order_list_returns_none_when_nothing_needs_reordering():
    products = [{"name": "Fine", "suggested_reorder_quantity": 0}]
    assert _build_priority_order_list(products) is None


def test_build_priority_order_list_truncates_and_reports_the_remainder():
    products = [
        {"name": f"Product {i}", "suggested_reorder_quantity": 1, "days_of_cover_at_forecast_rate": "0"}
        for i in range(_MAX_PRIORITY_LIST_DISPLAY + 5)
    ]
    built = _build_priority_order_list(products)
    assert built is not None
    text, truncated = built
    assert truncated is True
    assert "5 more product(s)" in text
