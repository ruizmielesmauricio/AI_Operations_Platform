"""Pure classification for the weekly consolidated stock review
notification (ORLA Notifications/Security/Retention prompt, section 2):
"out of stock", "stale", and "excess" counts. Same conventions as the
rest of app/analytics/ — plain inputs, no DB, no I/O — and deliberately
built on top of app/analytics/retail.py's own StockCoverRow/classify_
movers/find_dead_stock rather than a second, parallel stock-cover
calculation.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.analytics.retail import DeadStockEntry, StockCoverRow, classify_movers

# A product carrying at least this many times its own effective low-stock
# threshold in days-of-cover is "excess" — holding far more than the shop
# itself has decided (or ORLA has recommended) it needs on hand. Tied to
# each product's own configured/recommended threshold
# (app/analytics/replenishment.py, already deterministic and tested)
# rather than one arbitrary fixed day count that would mean something
# different for a fast-turning product than a slow one.
EXCESS_STOCK_COVER_MULTIPLIER = Decimal("3")


@dataclass(frozen=True)
class StockReviewSummary:
    out_of_stock_count: int
    stale_count: int
    excess_count: int


def classify_stock_review(
    stock_by_product: dict[uuid.UUID, int],
    stock_cover_rows: list[StockCoverRow],
    dead_stock_entries: list[DeadStockEntry],
    effective_threshold_by_product: dict[uuid.UUID, Decimal],
) -> StockReviewSummary:
    """"Do not classify items when evidence is incomplete" (the prompt's
    own requirement) is honoured throughout: out-of-stock needs only a
    current stock count, which is always known; stale reuses find_dead_
    stock/classify_movers, both of which already exclude a product with
    no real sales history to judge by; excess is only ever evaluated for
    a product with a *known* cover_days (real recent sales behind the
    estimate) — a product ORLA can't say how fast it sells can't be
    called "too much" stock either.
    """
    out_of_stock_count = sum(1 for stock in stock_by_product.values() if stock <= 0)

    movers = classify_movers(stock_cover_rows)
    # "Stale" = genuinely stopped moving (dead stock — real stock on hand,
    # zero sales in the lookback window) or moving very slowly
    # (classify_movers' own slow_movers bucket, cover_days >= 60). A
    # product can be flagged by at most one of the two (dead stock has no
    # cover_days at all, so it's never also a slow_mover), but a set
    # union keeps this correct even if that ever changes.
    stale_ids = {e.product_id for e in dead_stock_entries} | {r.product_id for r in movers.slow_movers}
    stale_count = len(stale_ids)

    excess_count = 0
    for row in stock_cover_rows:
        if row.cover_days is None:
            continue  # no real sales evidence to judge "too much" against
        threshold = effective_threshold_by_product.get(row.product_id)
        if threshold is None or threshold <= 0:
            continue
        if row.cover_days >= threshold * EXCESS_STOCK_COVER_MULTIPLIER:
            excess_count += 1

    return StockReviewSummary(out_of_stock_count=out_of_stock_count, stale_count=stale_count, excess_count=excess_count)
