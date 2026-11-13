from app.ai.glossary import match_definition_question


def test_definition_question_matches_the_glossary():
    assert match_definition_question("What does revenue mean?") == "revenue"


def test_my_revenue_question_is_not_treated_as_a_definition():
    assert match_definition_question("What's my revenue across all branches?") is None


def test_our_revenue_question_is_not_treated_as_a_definition():
    assert match_definition_question("What is our revenue this month?") is None


def test_compound_question_is_not_short_circuited_to_a_definition():
    # ORLA-91: the stock half of this question used to be dropped.
    assert match_definition_question("How much stock of Chain Lube do I have, and what does gross margin mean?") is None
    assert match_definition_question("What does gross margin mean and what should I reorder?") is None


def test_single_definition_question_with_trailing_punctuation_still_matches():
    assert match_definition_question("What does gross margin mean?") == "gross_margin"
    assert match_definition_question("Explain what stock cover is.") == "stock_cover"
