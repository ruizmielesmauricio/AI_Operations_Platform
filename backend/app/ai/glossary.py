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

METRIC_DEFINITIONS: dict[str, str] = {
    "revenue": "Total sales recorded in the selected period.",
    "gross_margin": (
        "Revenue minus the cost of goods sold, as a percentage of revenue with a known cost — "
        "it's what's left in cash after paying for the stock that was sold, out of total revenue."
    ),
    "cost_coverage": "The share of revenue where a cost price was actually recorded — margin below this is only an estimate.",
    "tax_coverage": (
        "The share of cost-known revenue that also has a confirmed tax figure, letting margin be computed "
        "net of tax rather than assumed."
    ),
    "stock_cover": "How many days of stock are left at the recent sales rate. Blank means not enough recent sales to estimate.",
    "dead_stock": "Products with stock on hand but zero sales in the selected period at all.",
    "fast_movers": "Products selling through quickly — 14 days of stock cover or less.",
    "slow_movers": "Products with 60 or more days of stock cover — a candidate for a discount, bundle, or supplier return.",
    "inventory_turnover": (
        "Cost of goods sold divided by current inventory value at cost — a simplification, since it uses current "
        "inventory value rather than a true period-average."
    ),
    "sell_through": "Units sold divided by units sold plus stock still on hand — an approximation, not an exact sell-through rate.",
    "workshop_margin": "Price charged minus labour cost. Parts cost isn't tracked yet, so this understates true repair cost.",
    "revenue_forecast": (
        "A plain projection from recent sales history — the average for that weekday if there's enough history, "
        "otherwise a plain recent average. Not AI, just deterministic math. The typical range shown is how much "
        "that history has varied, not a statistical guarantee."
    ),
    "reorder_suggestion": (
        "A starting suggestion only: the forecast's upper estimate minus current stock. It doesn't know your "
        "supplier's lead time or how much safety buffer you want."
    ),
    "low_stock": "A product whose stock on hand has fallen below its configured (or default) reorder threshold.",
}

ALLOWED_METRIC_KEYS = tuple(METRIC_DEFINITIONS.keys())

_DEFINITION_TRIGGER_WORDS = ("what does", "what is", "what's", "define", "explain what", "meaning of")

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue",),
    "gross_margin": ("gross margin", "margin"),
    "cost_coverage": ("cost coverage", "cost data coverage"),
    "tax_coverage": ("tax coverage",),
    "stock_cover": ("stock cover", "days of stock", "cover days"),
    "dead_stock": ("dead stock",),
    "fast_movers": ("fast mover", "fast movers"),
    "slow_movers": ("slow mover", "slow movers"),
    "inventory_turnover": ("inventory turnover", "turnover"),
    "sell_through": ("sell-through", "sell through"),
    "workshop_margin": ("workshop margin", "labour margin", "repair margin"),
    "revenue_forecast": ("revenue forecast", "sales forecast"),
    "reorder_suggestion": ("reorder suggestion", "suggested reorder", "reorder quantity"),
    "low_stock": ("low stock", "low-stock"),
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
    if not any(trigger in lowered for trigger in _DEFINITION_TRIGGER_WORDS):
        return None
    for key, aliases in _METRIC_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return key
    return None
