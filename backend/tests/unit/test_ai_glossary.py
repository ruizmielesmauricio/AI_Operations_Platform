from app.ai.glossary import match_definition_question


def test_definition_question_matches_the_glossary():
    assert match_definition_question("What does revenue mean?") == "revenue"


def test_my_revenue_question_is_not_treated_as_a_definition():
    assert match_definition_question("What's my revenue across all branches?") is None


def test_our_revenue_question_is_not_treated_as_a_definition():
    assert match_definition_question("What is our revenue this month?") is None
