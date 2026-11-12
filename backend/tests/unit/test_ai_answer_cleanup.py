from app.ai.service import _clean_ai_text, _with_margin_coverage_note


def test_lines_leaking_context_field_names_are_dropped():
    # Live failure: "- suggested_reorder_quantity: 49 units" lines in a reorder answer.
    context = {"products": [{"name": "Helmet", "suggested_reorder_quantity": 49}]}
    text = "You should reorder:\n- Helmet: 49 units\n- suggested_reorder_quantity: 49 units"
    assert _clean_ai_text(text, context) == "You should reorder:\n- Helmet: 49 units"


def test_sentence_repeated_back_to_back_is_collapsed():
    # Live failure: "You have -499 units of Inner Tube 29x2.2 in stock.You have -499 ..."
    text = "You have -499 units of Inner Tube 29x2.2 in stock.You have -499 units of Inner Tube 29x2.2 in stock."
    assert _clean_ai_text(text, {}) == "You have -499 units of Inner Tube 29x2.2 in stock."


def test_normal_answer_is_unchanged():
    text = "Revenue was €40,461.18 from 13 Oct to 11 Nov, up 40.4%. Inner tubes sold best."
    assert _clean_ai_text(text, {"revenue": {"current": "40461.18"}}) == text


def test_never_returns_empty():
    context = {"suggested_reorder_quantity": 1}
    assert _clean_ai_text("suggested_reorder_quantity", context) == "suggested_reorder_quantity"


def test_low_cost_coverage_adds_a_warning_note():
    ctx = _with_margin_coverage_note({"gross_margin": {"cost_data_coverage_pct": "0.0"}})
    assert "margin_data_warning" in ctx


def test_good_cost_coverage_adds_no_note():
    ctx = _with_margin_coverage_note({"gross_margin": {"cost_data_coverage_pct": "95.0"}})
    assert "margin_data_warning" not in ctx
