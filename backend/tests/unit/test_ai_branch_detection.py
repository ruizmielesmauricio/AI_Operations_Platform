"""Covers app/ai/service.py::_detect_named_business — the deterministic
(not classify-prompt-based) check that lets a chat question naming one of
the account's own branches by name override whatever business/all_branches
scope was otherwise selected. Pure function, hand-built Business objects,
no DB needed.
"""

from app.ai.service import _detect_named_business
from app.models.business import Business


def _business(name: str) -> Business:
    return Business(name=name, template="bicycle_shop", timezone="Europe/Dublin")


def test_matches_a_business_named_in_the_question():
    galway = _business("Galway")
    dublin = _business("Test Bike Shop")
    result = _detect_named_business("What was revenue at the Galway branch last week?", [galway, dublin])
    assert result is galway


def test_no_match_returns_none():
    galway = _business("Galway")
    dublin = _business("Test Bike Shop")
    result = _detect_named_business("How is my revenue doing?", [galway, dublin])
    assert result is None


def test_matching_is_case_insensitive():
    galway = _business("Galway")
    result = _detect_named_business("what about galway this month", [galway])
    assert result is galway


def test_matching_is_whole_word_not_a_bare_substring():
    # A short business name shouldn't accidentally match inside an
    # unrelated word — "Ely" (a real Irish town name) must not match
    # "likely".
    ely = _business("Ely")
    result = _detect_named_business("Is my revenue likely to grow?", [ely])
    assert result is None


def test_ambiguous_match_across_two_businesses_returns_none():
    # Two real, distinct businesses both happen to appear in the
    # question — deliberately not resolved by guessing which one was
    # meant; falls through to whatever scope was already selected.
    galway = _business("Galway")
    cork = _business("Cork")
    result = _detect_named_business("Compare Galway and Cork for me", [galway, cork])
    assert result is None


def test_a_multi_word_business_name_matches_as_a_phrase():
    shop = _business("Test Bike Shop")
    result = _detect_named_business("How did Test Bike Shop do last month?", [shop])
    assert result is shop
