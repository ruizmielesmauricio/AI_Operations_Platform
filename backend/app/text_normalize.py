"""Shared text-normalization helpers for ORLA's free-text lookup intents
(product/purchase/repair search) — one place to close a class of
"visually identical but a different Unicode codepoint" input mismatch,
rather than re-fixing it independently in every repository that does a
substring/exact match against user-supplied text.

Live-reproduced real bug: a client's own browser/keyboard sent
"E‑Motion Trail 500" with U+2011 (NON-BREAKING HYPHEN) in place of the
plain ASCII "-" (U+002D) actually stored in the product's name — a
byte-exact LIKE match silently found nothing even though the product
genuinely existed, and ORLA reported "I couldn't find anything matching"
for a real product a business owner was asking about. Purely
deterministic string normalization — never an AI-driven fuzzy match —
consistent with CLAUDE.md's Core Rule that this whole layer stays
deterministic Python.
"""

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

# Every common dash/hyphen-like character a keyboard, browser
# autocorrect/smart-punctuation feature, or a client's own spreadsheet
# export might reasonably produce in place of a plain ASCII hyphen-
# minus. Deliberately narrow — this closes a demonstrated, specific
# class of mismatch (visually identical dashes), not a general fuzzy-
# matching engine.
_DASH_VARIANTS = ("‐", "‑", "‒", "–", "—", "−")


def normalize_dashes(text: str) -> str:
    """Collapses every dash/hyphen-like Unicode variant in `text` to a
    plain ASCII "-" — applied to the incoming search term (Python-side)."""
    for variant in _DASH_VARIANTS:
        text = text.replace(variant, "-")
    return text


def normalize_dashes_column(column: ColumnElement) -> ColumnElement:
    """The SQL-side mirror of `normalize_dashes`, for wrapping a stored
    column/expression before comparison — a client's own imported data
    (a product name typed in a spreadsheet, say) could just as easily
    contain one of these variants as a chat question can, so both sides
    of a comparison are normalized, not just the query."""
    for variant in _DASH_VARIANTS:
        column = func.replace(column, variant, "-")
    return column
