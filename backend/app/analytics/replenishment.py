"""Deterministic low-stock threshold recommendation (Gap 1 / PR-9.3
follow-up). Pure — same conventions as workshop.py/financial.py: plain
Decimal inputs, quantized results, no DB, no I/O.

Per CLAUDE.md's Core Rule, ORLA/AI never calculates this — it only
explains a value this module already computed. The formula is
deliberately simple and legible rather than a black box: a recommended
threshold (in days of stock cover — the same unit
Product.low_stock_threshold_days already uses) is the known supplier lead
time plus a fixed safety buffer, falling back to the existing global
default when no lead time is known yet. "How quickly the item sells" is
informational context for the explanation, not an input to this formula —
app/analytics/retail.py's stock_cover/units_sold_in_period already answer
that and are passed through unchanged.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.analytics.findings import DEFAULT_LOW_STOCK_THRESHOLD_DAYS

# A flat, explainable cushion added on top of a known supplier lead time —
# covers ordinary variability (a slightly late delivery, a busier-than-
# usual week) without needing a second, harder-to-explain statistical
# input. Not configurable per business in this pass; a fixed constant is
# the "smallest coherent version" — a per-business override is a
# reasonable future refinement, not a functional gap today.
DEFAULT_SAFETY_BUFFER_DAYS = Decimal("3")

_TENTH_DAY = Decimal("0.1")


def _quantize_days(value: Decimal) -> Decimal:
    return value.quantize(_TENTH_DAY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ThresholdRecommendation:
    recommended_threshold_days: Decimal
    # "supplier_lead_time" when a known lead time drove the number,
    # "default_fallback" when no supplier lead time is known yet — the UI
    # and any explanation text branch on this rather than guessing why a
    # number is what it is.
    basis: str
    lead_time_days: Decimal | None
    safety_buffer_days: Decimal
    current_threshold_days: Decimal | None


def recommend_low_stock_threshold(
    *,
    lead_time_days: Decimal | None,
    current_threshold_days: Decimal | None,
    safety_buffer_days: Decimal = DEFAULT_SAFETY_BUFFER_DAYS,
) -> ThresholdRecommendation:
    if lead_time_days is not None:
        recommended = _quantize_days(lead_time_days + safety_buffer_days)
        basis = "supplier_lead_time"
    else:
        recommended = DEFAULT_LOW_STOCK_THRESHOLD_DAYS
        basis = "default_fallback"

    return ThresholdRecommendation(
        recommended_threshold_days=recommended,
        basis=basis,
        lead_time_days=lead_time_days,
        safety_buffer_days=safety_buffer_days,
        current_threshold_days=current_threshold_days,
    )
