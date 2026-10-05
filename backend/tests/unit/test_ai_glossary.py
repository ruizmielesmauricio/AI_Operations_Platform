from app.ai.glossary import match_definition_question


def test_definition_question_matches_the_glossary():
    assert match_definition_question("What does revenue mean?") == "revenue"


def test_my_revenue_question_is_not_treated_as_a_definition():
    assert match_definition_question("What's my revenue across all branches?") is None


def test_our_revenue_question_is_not_treated_as_a_definition():
    assert match_definition_question("What is our revenue this month?") is None


def test_a_definition_plus_another_question_is_not_answered_by_the_free_shortcut_alone():
    # The shortcut would answer only the definition and silently drop the
    # second half; the classifier has to see it so it can split the question.
    assert match_definition_question("What does gross margin mean and what is mine?") is None
    assert match_definition_question("What does dead stock mean? Also, what should I reorder?") is None


def test_plain_english_names_used_on_screen_match_the_glossary():
    assert match_definition_question("What does profit margin mean?") == "gross_margin"
    assert match_definition_question("What does reorder level mean?") == "reorder_level"
    assert match_definition_question("What is a slow seller?") == "slow_movers"
    assert match_definition_question("What does share of stock sold mean?") == "sell_through"
    assert match_definition_question("What does stock that isn't selling mean?") == "dead_stock"
    assert match_definition_question("What does SKU mean?") == "sku"
    assert match_definition_question("what does delivery time mean") == "lead_time"


def test_looser_openers_only_count_when_the_question_is_just_the_term():
    assert match_definition_question("What's a fast mover?") == "fast_movers"
    assert match_definition_question("What is a good margin for a shop like mine?") is None
    assert match_definition_question("What are my slow movers?") is None
    assert match_definition_question("What are the fast movers?") is None


def test_a_bare_what_is_term_question_is_a_free_definition():
    assert match_definition_question("What is stock cover?") == "stock_cover"
    assert match_definition_question("what's sell through") == "sell_through"
    assert match_definition_question("What is inventory turnover?") == "inventory_turnover"
    assert match_definition_question("What is suggested reorder?") == "reorder_suggestion"
    assert match_definition_question("What is my stock cover?") is None


def test_whats_running_low_is_a_question_about_the_data_not_a_definition():
    assert match_definition_question("What's running low?") is None
    assert match_definition_question("what is low stock") == "low_stock"
