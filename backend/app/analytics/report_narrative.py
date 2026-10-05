"""Deterministic plain-language summary sentences for Stage D17/D18's
scheduled reports — PR-8.3 point 5's "deterministic summary of the most
material performance changes." Template strings with already-computed
numbers plugged in, nothing else — no AI, no free-text generation
(PR-8.7: "all numbers, summaries, projections, and recommendations trace
to backend calculations, templates, or rules"). Pure, same conventions as
app/analytics/findings.py: narrow input types (not the DB-touching
application-layer summaries), no DB, no I/O.
"""

from decimal import Decimal

from app.analytics.financial import RevenueTrend

# Below this magnitude, a revenue swing reads as "broadly stable" rather
# than claiming a trend the data doesn't clearly support.
_MATERIAL_CHANGE_THRESHOLD_PCT = Decimal("5")


def build_executive_narrative(
    *,
    revenue: RevenueTrend,
    low_stock_count: int,
    dead_stock_count: int,
    top_recommendation_title: str | None,
) -> list[str]:
    """A short, fixed-order list of plain sentences — the report's
    "Overall Performance" paragraph. Order is deliberately fixed (revenue
    direction, then stock health, then the single most material
    recommendation) rather than ranked by any logic of its own; the
    ranking already happened upstream (compute_revenue_change,
    build_stock_cover_report, build_recommendations).
    """
    sentences: list[str] = []

    if revenue.change_pct is None:
        sentences.append(f"Sales this period were {revenue.current}. There's no earlier period to compare with yet.")
    elif revenue.change_pct >= _MATERIAL_CHANGE_THRESHOLD_PCT:
        sentences.append(f"Sales were up {revenue.change_pct}% compared with the previous period.")
    elif revenue.change_pct <= -_MATERIAL_CHANGE_THRESHOLD_PCT:
        sentences.append(f"Sales were down {abs(revenue.change_pct)}% compared with the previous period.")
    else:
        sentences.append(f"Sales were about the same as the previous period ({revenue.change_pct}%).")

    if dead_stock_count > 0:
        sentences.append(f"{dead_stock_count} product(s) are in stock but didn't sell at all this period.")
    if low_stock_count > 0:
        sentences.append(f"{low_stock_count} product(s) are running low.")
    if low_stock_count == 0 and dead_stock_count == 0:
        sentences.append("No products are running low, and nothing is sitting unsold.")

    if top_recommendation_title:
        sentences.append(f"The highest-priority recommendation this period: {top_recommendation_title}.")

    return sentences
