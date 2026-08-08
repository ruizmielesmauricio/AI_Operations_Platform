"""Covers app/imports/importer.py::CategoryMatcher — the import-time
category name resolver backing the new "category" optional field on
sales/purchases/inventory uploads. Mirrors test_importer_grouping.py's
ProductMatcher test conventions (a pure, in-memory, no-DB class)."""

from app.imports.importer import CategoryMatcher, normalize_category_name


class _FakeCategory:
    def __init__(self, id, name):
        self.id = id
        self.name = name


def test_normalize_category_name_is_case_and_whitespace_insensitive():
    assert normalize_category_name("  Chain   Parts ") == normalize_category_name("chain parts") == "chain parts"


def test_resolve_matches_an_existing_category_by_normalized_name():
    matcher = CategoryMatcher([_FakeCategory("c1", "Parts")])
    resolved = matcher.resolve("parts")
    assert resolved is not None
    assert resolved.id == "c1"


def test_resolve_is_whitespace_insensitive():
    matcher = CategoryMatcher([_FakeCategory("c1", "Bike Parts")])
    resolved = matcher.resolve("  bike   parts  ")
    assert resolved is not None
    assert resolved.id == "c1"


def test_resolve_returns_none_for_an_unseen_category_name():
    matcher = CategoryMatcher([_FakeCategory("c1", "Parts")])
    assert matcher.resolve("Accessories") is None


def test_register_created_makes_a_new_category_resolvable_on_a_later_row_in_the_same_file():
    matcher = CategoryMatcher([])
    assert matcher.resolve("Nutrition") is None
    matcher.register_created(_FakeCategory("new-id", "Nutrition"))
    resolved = matcher.resolve("nutrition")
    assert resolved is not None
    assert resolved.id == "new-id"


def test_two_categories_differing_only_by_case_or_whitespace_resolve_to_the_same_one():
    matcher = CategoryMatcher([_FakeCategory("c1", "Bike Parts")])
    first = matcher.resolve("Bike Parts")
    second = matcher.resolve("bike  parts")
    assert first is not None and second is not None
    assert first.id == second.id == "c1"
