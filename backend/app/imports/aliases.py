"""Canonical field definitions and the alias dictionary (PR-2.3) — layer 1
of the detection engine (app/imports/detection.py). Kept deliberately
industry-agnostic: "sales" is a canonical, cross-industry entity per
docs/governance/06_Database_Design.md's three-layer model, and no
bicycle-specific terms belong here. Customer name/email/phone are
deliberately not mappable fields (data minimisation — no feature today
needs customer-level PII, and Sale.customer_id is optional).

Adding a new entity_type or canonical field later is additive: extend
CANONICAL_FIELDS/ALIASES, no changes to detection.py's algorithm.
"""

import re

SUPPORTED_ENTITY_TYPES = ("sales",)

# Field order matters: it's the priority order alias matching resolves
# ties in (see match_alias) and the order fields are presented for
# confirmation.
CANONICAL_FIELDS: dict[str, list[str]] = {
    "sales": [
        "sale_date",
        "product_name",
        "sku",
        "quantity",
        "unit_price",
        "total_amount",
        "cost_price_at_sale",
        "order_reference",
    ]
}

# Every field's canonical name is itself a valid alias (normalized), so
# these lists only need to cover real-world variants seen across common
# POS/spreadsheet exports (Lightspeed, EPOS Now, Vend, Shopify POS,
# Cybertill, plain accounting exports).
ALIASES: dict[str, dict[str, list[str]]] = {
    "sales": {
        "sale_date": [
            "sale date", "transaction date", "txn date", "order date", "sold date",
            "invoice date", "receipt date", "date of sale", "created date", "order_date",
            "posting date", "date",
        ],
        "product_name": [
            "item", "product", "description", "product name", "item description",
            "item name", "sku description", "product description", "name", "title",
            "line item",
        ],
        "sku": [
            "sku", "product code", "item code", "barcode", "product sku", "item sku",
            "code", "upc", "item#", "item number",
        ],
        "quantity": [
            "qty", "quantity", "units", "units sold", "qty sold", "number sold", "count",
        ],
        "unit_price": [
            "price", "unit price", "sale price", "sell price", "item price",
            "price each", "rate", "price/unit", "unit sell price",
        ],
        "total_amount": [
            "total", "amount", "total amount", "line total", "grand total",
            "net amount", "total price", "revenue", "sale amount", "sub total",
            "subtotal",
        ],
        "cost_price_at_sale": [
            "cost", "cost price", "unit cost", "cogs", "cost of goods", "item cost",
        ],
        # Groups several imported rows into one multi-item Sale (Sale.order_reference).
        # Deliberately excludes "register"/"register number": a till/register
        # number identifies which terminal rang up a sale, not the individual
        # transaction, so grouping by it would merge unrelated sales together.
        "order_reference": [
            "order id", "order number", "order no", "order ref", "order reference",
            "receipt number", "receipt no", "receipt ref", "transaction id",
            "transaction number", "txn id", "txn number", "invoice number",
            "invoice no", "reference number", "reference",
        ],
    }
}

_PUNCTUATION_RE = re.compile(r"[_\-.:]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_header(text: str) -> str:
    """Case/whitespace/punctuation-insensitive form used for alias matching
    and source_signature computation — "Sale Date", "sale_date", and
    " Sale-Date " must all resolve identically.
    """
    text = _PUNCTUATION_RE.sub(" ", text.strip().lower())
    return _WHITESPACE_RE.sub(" ", text).strip()


def match_alias(header_name: str, entity_type: str) -> str | None:
    """Layer 1: exact match (after normalization) against the alias
    dictionary. Returns the canonical field name, or None if nothing
    matches — the column falls through to structural heuristics (layer 2).
    """
    # normalize_header collapses "_"/"-" to spaces, so a header matching the
    # literal canonical field name (e.g. "sale_date" -> "sale date") already
    # matches that field's alias list below — no separate equality check needed.
    normalized = normalize_header(header_name)
    if not normalized:
        return None
    for field in CANONICAL_FIELDS[entity_type]:
        if normalized in ALIASES[entity_type][field]:
            return field
    return None
