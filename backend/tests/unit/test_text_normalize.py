"""Covers app/text_normalize.py — live-reproduced real bug: a search
term containing a non-ASCII dash/hyphen variant (e.g. U+2011 NON-
BREAKING HYPHEN from a real customer's own browser/keyboard) silently
matched nothing against a stored value using a plain ASCII hyphen, even
though the two are visually identical and refer to the same thing.
"""

from sqlalchemy import select

from app.text_normalize import normalize_dashes, normalize_dashes_column


def test_normalize_dashes_collapses_every_known_variant_to_ascii_hyphen():
    variants = "‐ ‑ ‒ – — −"
    assert normalize_dashes(variants) == "- - - - - -"


def test_normalize_dashes_leaves_a_plain_ascii_hyphen_and_other_text_untouched():
    assert normalize_dashes("E-Motion Trail 500") == "E-Motion Trail 500"


def test_normalize_dashes_matches_the_exact_reported_transcript():
    # The literal reported question: "How many E‑Motion Trail 500 did I
    # order last time?" — the hyphen here is U+2011, not the ASCII "-"
    # actually stored in the product's real name.
    reported = "E‑Motion Trail 500"
    assert normalize_dashes(reported) == "E-Motion Trail 500"


def test_normalize_dashes_column_chains_one_replace_per_dash_variant():
    # A lightweight compile-only check (no DB round trip needed here —
    # the actual matching behavior is exercised end to end in
    # tests/integration/test_ai_chat.py) that the SQL expression is at
    # least well-formed and chains every variant.
    from app.models.product import Product

    expr = normalize_dashes_column(Product.name)
    compiled = str(select(expr).compile())
    assert compiled.lower().count("replace(") == 6  # one REPLACE() per dash variant
