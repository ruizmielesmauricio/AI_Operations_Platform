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
from collections.abc import Callable

SUPPORTED_ENTITY_TYPES = ("sales", "inventory", "purchases", "repairs")

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
        # Optional — when a POS export's total is tax-inclusive (the usual
        # source of an apparent total_amount_mismatch), mapping this lets
        # margin be computed net of tax instead of just flagging the
        # mismatch. Never required (MINIMUM_MAPPING_RULES below doesn't
        # reference it) — see app/imports/importer.py::validate_and_parse_row
        # and app/analytics/financial.py's net_gross_margin_pct.
        "tax_amount",
        "order_reference",
        # Optional — see the shared _CATEGORY_ALIASES comment below.
        # Resolves against ProductCategory by name (match-or-create, same
        # pattern as product SKU/name matching); never required
        # (MINIMUM_MAPPING_RULES below doesn't reference it).
        "category",
        # Optional — see the shared _LOCATION_ALIASES comment below. Never
        # persisted anywhere (no Product/Sale table gains a location
        # column) — purely a pre-import signal app/imports/service.py::
        # confirm_mapping checks for more than one distinct value and
        # blocks on, since that's a strong sign a file combines more than
        # one physical location's data into a single business (each
        # location should be its own branch — direct request).
        "location",
    ],
    # A stock-count snapshot, not a transaction: one row per product's
    # current on-hand quantity.
    "inventory": [
        "product_name",
        "sku",
        "quantity_on_hand",
        # Optional — a stock-count export sometimes carries per-unit cost
        # alongside the count. Not required (MINIMUM_MAPPING_RULES below
        # never references it), same "optional, never blocks a row"
        # treatment as purchases' unit_cost — see
        # app/imports/importer.py::validate_and_parse_inventory_row. Lets a
        # shop that never uploads a separate purchases file still set
        # Product.cost_price.
        "unit_cost",
        # Optional — see the shared _CATEGORY_ALIASES comment below.
        "category",
        # Optional — see the shared _LOCATION_ALIASES comment above.
        "location",
        # Optional — supersedes an earlier "inventory has no date field by
        # design" decision (that design assumed reconciliation always
        # compares against whatever's *currently* derived, which is
        # exactly what made a purchase/sale dated before a stock count
        # capable of double-counting stock — see
        # app/imports/importer.py::sum_by_product_ids's date-aware
        # rewrite). Most exports won't have this column at all; when
        # absent, defaults to the upload's own processing date in the
        # business's timezone, which is exactly today's prior behavior.
        "as_of_date",
    ],
    # A restocking transaction — each row is its own independent fact
    # ("we received N units on this date"), not a reconciliation like
    # "inventory" above. No order/PO-level grouping (unlike sales'
    # order_reference): each row becomes its own InventoryMovement.
    "purchases": [
        "purchase_date",
        "product_name",
        "sku",
        "quantity_received",
        "unit_cost",
        # Optional — a PO/invoice number, if the export has one. Lets a
        # re-uploaded/overlapping file be rejected instead of silently
        # double-counting stock received. Never required
        # (MINIMUM_MAPPING_RULES below never references it) — see
        # app/imports/importer.py::validate_and_parse_purchase_row.
        "purchase_reference",
        # Optional — see the shared _CATEGORY_ALIASES comment below.
        "category",
        # Optional — matched against existing suppliers by normalized
        # name, match-or-create, same exact pattern as "category" just
        # above — never required (MINIMUM_MAPPING_RULES below doesn't
        # reference it). See app/models/supplier.py.
        "supplier",
        # Optional — see the shared _LOCATION_ALIASES comment above.
        "location",
    ],
    # One row per finished repair, from a shop's own workshop log/export —
    # treated the same as sales at the row level, not the line-item level
    # (no parts-consumed detail here; see app/models/production_event.py).
    "repairs": [
        "repair_date",
        "description",
        "price_charged",
        "labour_cost",
        # Optional — same reasoning as sales' tax_amount above: when
        # price_charged is tax-inclusive (a very common shape for a
        # workshop invoice total), mapping this lets workshop margin be
        # computed net of tax instead of silently overstating it. Never
        # required (MINIMUM_MAPPING_RULES below doesn't reference it) —
        # see app/imports/importer.py::validate_and_parse_repair_row and
        # app/analytics/workshop.py's net_gross_margin_pct.
        "tax_amount",
        # Optional — same reasoning as purchases' purchase_reference above,
        # for workshop revenue instead of stock.
        "repair_reference",
        # Optional — see the shared _LOCATION_ALIASES comment above. Unlike
        # "category" (deliberately excluded here — ProductionEvent has no
        # product_id to hang a category off), a repair's own location is a
        # first-class attribute of the repair row itself, no FK gap to work
        # around.
        "location",
    ],
}

# Declarative per-entity-type "is this mapping usable at all" check —
# app/imports/service.py's confirm_mapping() uses this instead of an
# if/elif chain, keeping this file's "extend the dicts" promise intact.
MINIMUM_MAPPING_RULES: dict[str, Callable[[dict[str, str | None]], bool]] = {
    "sales": lambda m: bool(m.get("sale_date")) and bool(m.get("unit_price") or m.get("total_amount")),
    "inventory": lambda m: bool(m.get("product_name") or m.get("sku")) and bool(m.get("quantity_on_hand")),
    "purchases": lambda m: (
        bool(m.get("purchase_date"))
        and bool(m.get("product_name") or m.get("sku"))
        and bool(m.get("quantity_received"))
    ),
    "repairs": lambda m: (
        bool(m.get("repair_date"))
        and bool(m.get("description") or m.get("price_charged") or m.get("labour_cost"))
    ),
}

# Shared between purchases' unit_cost and inventory's optional unit_cost —
# one list, not two, so they can't silently drift apart.
_UNIT_COST_ALIASES = [
    "unit cost", "cost", "cost price", "cost/unit", "cost each",
    "purchase price", "supplier price", "landed cost", "buy price",
]

# Shared across sales/inventory/purchases — a plain text field, not a
# money field, so (unlike unit_cost) it never needs a detection.py
# structural-scoring entry, matching purchase_reference/repair_reference's
# treatment. Resolved at import time against ProductCategory by normalized
# name (match existing, or create — same match-or-create shape as product
# SKU/name resolution, see app/imports/importer.py). Deliberately not
# offered on "repairs": ProductionEvent has no product_id at all (no live
# FK path to a category exists for a repair). Kept industry-agnostic per
# this file's own stated convention — "category"/"department"/"type" cover
# a bike shop's parts categories just as well as a cafe's menu sections or
# a pharmacy's product classes.
_CATEGORY_ALIASES = [
    "category", "product category", "department", "type", "product type",
    "product group", "group", "class", "classification",
]

# Shared across sales/inventory/purchases/repairs — direct request: a
# real, deterministic signal that an uploaded file combines more than one
# physical location's data into a single business (avoiding the €30/
# month branch fee each additional one should be billed separately —
# BD-007). Deliberately not resolved against anything or written to the
# database anywhere (no Product/Sale/ProductionEvent table gains a
# location column) — purely a pre-import check
# (app/imports/service.py::confirm_mapping counts distinct values in
# whichever column this resolves to and blocks, with an explicit
# override, when there's more than one). Kept industry-agnostic per this
# file's own convention: "store"/"branch"/"outlet"/"site" all describe
# the same concept a bike shop, a cafe, or a pharmacy chain would each
# use their own term for.
_LOCATION_ALIASES = [
    "location", "store", "store name", "store id", "branch", "branch name",
    "shop", "outlet", "site", "location name", "location id",
]

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
        "tax_amount": [
            "tax", "vat", "tax amount", "vat amount", "sales tax", "tax charged",
            "total tax", "gst",
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
        "category": _CATEGORY_ALIASES,
        "location": _LOCATION_ALIASES,
    },
    "inventory": {
        "product_name": [
            "item", "product", "description", "product name", "item description",
            "item name", "sku description", "product description", "name", "title",
        ],
        "sku": [
            "sku", "product code", "item code", "barcode", "product sku", "item sku",
            "code", "upc", "item#", "item number",
        ],
        "quantity_on_hand": [
            "qty on hand", "quantity on hand", "stock", "stock level", "stock count",
            "on hand", "current stock", "inventory count", "quantity in stock",
            "units in stock", "available stock", "stock qty",
        ],
        "unit_cost": _UNIT_COST_ALIASES,
        "category": _CATEGORY_ALIASES,
        "location": _LOCATION_ALIASES,
        "as_of_date": [
            "as of date", "count date", "stock date", "snapshot date", "date counted",
            "inventory date", "date",
        ],
    },
    "purchases": {
        "purchase_date": [
            "purchase date", "date received", "received date", "delivery date",
            "restock date", "po date", "order date", "date",
        ],
        "product_name": [
            "item", "product", "description", "product name", "item description",
            "item name", "sku description", "product description", "name", "title",
        ],
        "sku": [
            "sku", "product code", "item code", "barcode", "product sku", "item sku",
            "code", "upc", "item#", "item number",
        ],
        "quantity_received": [
            "qty received", "quantity received", "units received", "qty",
            "quantity", "units", "qty delivered", "restock qty", "amount received",
        ],
        "unit_cost": _UNIT_COST_ALIASES,
        "purchase_reference": [
            "po number", "purchase order", "po", "invoice number", "reference", "order number",
            # Found via Gate B testing with synthetic_orders.csv — none of
            # these real ERP column names matched anything above (this
            # entry list is exact-string-match only, no fuzzy/substring
            # matching exists anywhere in this engine).
            "purchase order id", "po id", "supplier order reference", "supplier invoice number",
        ],
        "category": _CATEGORY_ALIASES,
        "supplier": [
            "supplier", "vendor", "supplier name", "vendor name", "manufacturer",
            "supplied by", "ordered from",
        ],
        "location": _LOCATION_ALIASES,
    },
    "repairs": {
        "repair_date": [
            "repair date", "date repaired", "date completed", "completion date",
            "job date", "service date", "invoice date", "date",
        ],
        "description": [
            "description", "repair description", "work performed", "job description",
            "work done", "notes", "service description",
            # "notes" alone is a weak, often-empty free-text field in real
            # exports (Gate B testing found it winning over the genuinely
            # descriptive "issue_description" column purely because it
            # matched first) — this is the actual repair description.
            "issue description",
        ],
        "price_charged": [
            "price charged", "amount charged", "charge", "invoice amount",
            "invoice total", "total charged", "repair price", "service price",
            "amount", "total",
            # "amount"/"total" above only match a column named exactly
            # that one word — a two-word "Total Amount" header (a very
            # common real export shape, found via Gate B testing) matched
            # neither and fell through to structural scoring, where it
            # used to lose a tie to "labour_amount" (see detection.py's
            # _MONEY_TIE_EPSILON comment). Structural scoring now breaks
            # that tie correctly too, but a direct alias is a stronger,
            # zero-ambiguity signal.
            "total amount", "total price",
        ],
        "labour_cost": [
            "labour cost", "labor cost", "internal cost", "labour charge",
            # Found via Gate B testing: "labour_amount" (the real per-
            # repair labour cost in currency) used to lose a three-way
            # structural tie to "labour_hours" (a duration, not a cost —
            # see detection.py's _MONEY_TIE_EPSILON comment for the full
            # mechanism) purely because it appeared first in the file.
            "labour amount", "labor amount",
        ],
        "tax_amount": [
            "tax", "vat", "tax amount", "vat amount", "sales tax", "tax charged",
            "total tax", "gst",
        ],
        "repair_reference": [
            "job number", "invoice number", "reference", "work order", "ticket number",
        ],
        "location": _LOCATION_ALIASES,
    },
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
