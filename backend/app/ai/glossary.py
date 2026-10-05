"""A static metric glossary — the `metric_definition` intent's entire
answer comes straight from here, with zero AI generation involved (see
app/ai/service.py::fetch_context). "What does gross margin mean?" is a
fixed fact about how this platform computes a number, not something
that benefits from being phrased by a model, and answering it this way
costs nothing in tokens.

Mirrors (but doesn't share code with — frontend and backend are separate
codebases here) the DEFINITIONS map in frontend/app/dashboard/page.tsx;
keeping the two in sync by hand is an accepted, stated simplification
for this pass rather than building a shared source of truth.
"""

import re

METRIC_DEFINITIONS: dict[str, str] = {
    "revenue": "Your sales: the total you took from customers in the selected dates, after returns and refunds are taken off.",
    "gross_margin": (
        "Your profit margin: out of every €100 you sell, how many euro are left after paying for the stock itself "
        "(before rent, wages and other running costs). For example 40% means €40 of every €100 is yours. "
        "It only counts sales where ORLA knows what the item cost you."
    ),
    "cost_coverage": (
        "The share of your sales where ORLA knows what the item cost you. The lower it is, the less you should trust "
        "the profit margin. Add cost prices to your products to raise it."
    ),
    "tax_coverage": (
        "The share of sales where the VAT amount is known. Where it's missing, ORLA can't separate VAT from your "
        "profit, so margins may look a little higher than they really are."
    ),
    "stock_cover": (
        "Days of stock left: how many days your current stock should last if you keep selling at the recent pace. "
        "Blank means there haven't been enough recent sales to tell."
    ),
    "dead_stock": "Stock that isn't selling: products on your shelves that haven't sold at all in the selected dates.",
    "fast_movers": "Fast sellers: products that will sell out quickly — 14 days of stock left or less at the recent pace.",
    "slow_movers": (
        "Slow sellers: products with 60 or more days of stock left at the recent pace. "
        "Consider a discount, a bundle, or returning some to the supplier."
    ),
    "inventory_turnover": (
        "Stock turnover: how many times over you sold through the stock on your shelves in the period. "
        "A higher number means your money isn't sitting idle in stock."
    ),
    "sell_through": (
        "Share of stock sold: of everything you had to sell (sold plus still on the shelf), the share that actually "
        "sold. Higher usually means you're buying the right things."
    ),
    "workshop_margin": (
        "Repair profit (labour only): what you charged for repairs minus what the labour cost you. "
        "The cost of parts isn't tracked yet, so the real profit is a little lower."
    ),
    "revenue_forecast": (
        "A simple estimate of your next sales from your recent history (your usual pattern for each day of the week, "
        "or a plain average if there isn't much history yet). It isn't AI and it isn't a promise — the range shown is "
        "how much your sales have normally varied."
    ),
    "reorder_suggestion": (
        "Suggested order: a starting point for how many to order — the most ORLA expects you to sell minus what you "
        "already have. It doesn't know your supplier's delivery time, so sanity-check it before ordering."
    ),
    "low_stock": (
        "Running low: a product that has dropped to its reorder level — the number of days of stock left at which "
        "ORLA warns you to order more."
    ),
    "reorder_level": (
        "Reorder level: for each product, how low its stock can get before ORLA tells you to order more, measured "
        "in days of stock left. 14 means 'warn me when I have about two weeks left at the current pace'. "
        "You can change it for a product or a whole category."
    ),
    "sku": (
        "Product code (SKU): the code that identifies a product — on your price label, till or supplier invoice. "
        "If you don't use codes, ORLA matches on the product name instead."
    ),
    "lead_time": "Delivery time: how many days a supplier usually takes from you ordering to the stock arriving.",
}

ALLOWED_METRIC_KEYS = tuple(METRIC_DEFINITIONS.keys())

_ALSO_ASKS = re.compile(
    r"(?:\band\b|\balso\b|\bplus\b|\bthen\b|,)\s+(?:what|how|which|who|where|when|is|are|do|does|did|can|should|show|tell|give)\b"
)

_DEFINITION_TRIGGER_WORDS = ("what does", "define", "explain what", "meaning of", "what do you mean")
# "What is a slow mover?" / "what's sell through" are definitions — but "what is a
# good margin for a shop?" is advice. These looser openers only count when the question ends
# right after the term itself.
_BARE_TERM_OPENERS = ("what is ", "what's ", "what are ")

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue",),
    "gross_margin": ("gross margin", "profit margin", "margin"),
    "cost_coverage": ("cost coverage", "cost data coverage"),
    "tax_coverage": ("tax coverage",),
    "stock_cover": ("stock cover", "days of stock", "cover days"),
    "dead_stock": ("dead stock", "stock that isn't selling", "stock that isnt selling"),
    "fast_movers": ("fast mover", "fast movers", "fast seller"),
    "slow_movers": ("slow mover", "slow movers", "slow seller"),
    "inventory_turnover": ("inventory turnover", "turnover"),
    "sell_through": ("sell-through", "sell through", "share of stock sold"),
    "workshop_margin": ("workshop margin", "labour margin", "repair margin"),
    "revenue_forecast": ("revenue forecast", "sales forecast"),
    "reorder_suggestion": ("reorder suggestion", "suggested reorder", "reorder quantity"),
    "reorder_level": ("reorder level", "reorder point", "reorder threshold"),
    "low_stock": ("low stock", "low-stock"),
    "sku": ("sku", "product code"),
    "lead_time": ("lead time", "delivery time"),
}


def get_definition(metric_key: str) -> str | None:
    return METRIC_DEFINITIONS.get(metric_key)


def match_definition_question(question: str) -> str | None:
    """A cheap, fully deterministic pre-check (PR-5.5/cost-consciousness)
    that catches an obvious "what does X mean?"-style question before
    any AI call is made at all — genuinely zero AI cost, not just a
    cheap one. Returns the matched glossary key, or None if the
    question isn't confidently a definition question, in which case the
    caller (app/ai/service.py) falls through to the normal
    classify->fetch->explain pipeline, whose classifier can still land
    on the same `metric_definition` intent for phrasings this simple
    keyword check misses (at the cost of one small classify call)."""
    lowered = question.lower()
    # A question that asks for something else as well ("what does gross
    # margin mean and what is mine?") must go to the classifier, which can
    # split it — answering only the definition would silently drop the rest.
    if lowered.count("?") > 1 or _ALSO_ASKS.search(lowered):
        return None
    # "What's my revenue?" is asking for the business's actual number,
    # not the glossary entry for the word revenue. Keep the zero-cost
    # shortcut for clear definition phrasings only; the classifier can
    # still choose metric_definition for fuzzier cases after seeing the
    # full question.
    if re.search(r"\bwhat(?: is| are|'s)\s+(?:my|our|the|your)\b", lowered):
        return None
    bare_term = any(opener in lowered for opener in _BARE_TERM_OPENERS)
    if not bare_term and not any(trigger in lowered for trigger in _DEFINITION_TRIGGER_WORDS):
        return None
    stripped = lowered.rstrip("?!. ")
    for key, aliases in _METRIC_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                if bare_term and not any(trigger in lowered for trigger in _DEFINITION_TRIGGER_WORDS) and not stripped.endswith(alias):
                    continue
                return key
    return None
