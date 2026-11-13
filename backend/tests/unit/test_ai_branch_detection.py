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


# --- ORLA-91 eval findings -------------------------------------------------


def test_branch_named_in_full_wins_over_the_parent_name_inside_it():
    # "Debug Bike Shop Cork" contains the parent's own name — that used to
    # count as two matches (ambiguous) and the parent's figures were given.
    parent = _business("Debug Bike Shop")
    cork = _business("Debug Bike Shop Cork")
    result = _detect_named_business("What was revenue at Debug Bike Shop Cork last month?", [parent, cork])
    assert result is cork


def test_branch_named_by_its_distinctive_word():
    parent = _business("Debug Bike Shop")
    cork = _business("Debug Bike Shop Cork")
    result = _detect_named_business("How much did the Cork branch make?", [parent, cork])
    assert result is cork


def test_parent_named_alone_still_resolves_to_the_parent():
    parent = _business("Debug Bike Shop")
    cork = _business("Debug Bike Shop Cork")
    assert _detect_named_business("How is Debug Bike Shop doing?", [parent, cork]) is parent


def test_both_parent_and_branch_named_is_ambiguous():
    parent = _business("Debug Bike Shop")
    cork = _business("Debug Bike Shop Cork")
    assert _detect_named_business("Compare Debug Bike Shop and Debug Bike Shop Cork", [parent, cork]) is None


def test_shared_suffix_names_resolve_by_their_distinctive_word():
    cork = _business("Cork Bike Shop")
    galway = _business("Galway Bike Shop")
    assert _detect_named_business("revenue in galway?", [cork, galway]) is galway


def test_city_names_a_branch():
    main = _business("Spokes")
    branch = _business("Spokes Two")
    branch.city = "Limerick"
    assert _detect_named_business("How is Limerick doing?", [main, branch]) is branch


def test_generic_shared_words_are_never_an_alias():
    # Only "shop" differs — too generic to name a branch by.
    a = _business("Pedal Power")
    b = _business("Pedal Power Shop")
    assert _detect_named_business("how is the shop doing", [a, b]) is None
