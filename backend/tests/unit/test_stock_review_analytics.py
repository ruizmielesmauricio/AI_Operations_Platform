import uuid
from decimal import Decimal

from app.analytics.retail import DeadStockEntry, StockCoverRow
from app.analytics.stock_review import EXCESS_STOCK_COVER_MULTIPLIER, classify_stock_review

_P1, _P2, _P3, _P4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _cover_row(product_id, *, stock_on_hand, cover_days):
    return StockCoverRow(
        product_id=product_id, name="p", stock_on_hand=stock_on_hand, units_sold_in_period=1,
        cover_days=cover_days, revenue_in_period=Decimal("0"),
    )


def test_out_of_stock_counts_zero_and_negative_stock():
    stock_by_product = {_P1: 0, _P2: -1, _P3: 5}
    result = classify_stock_review(stock_by_product, [], [], {})
    assert result.out_of_stock_count == 2


def test_stale_includes_dead_stock_entries():
    dead = [DeadStockEntry(product_id=_P1, name="p", stock_on_hand=5, value_at_cost=None)]
    result = classify_stock_review({_P1: 5}, [], dead, {})
    assert result.stale_count == 1


def test_stale_includes_slow_movers():
    rows = [_cover_row(_P1, stock_on_hand=100, cover_days=Decimal("90"))]  # >= SLOW_MOVER_MIN_COVER_DAYS (60)
    result = classify_stock_review({_P1: 100}, rows, [], {})
    assert result.stale_count == 1


def test_stale_does_not_double_count_a_product_appearing_in_both_sources():
    dead = [DeadStockEntry(product_id=_P1, name="p", stock_on_hand=5, value_at_cost=None)]
    rows = [_cover_row(_P1, stock_on_hand=5, cover_days=Decimal("90"))]
    result = classify_stock_review({_P1: 5}, rows, dead, {})
    assert result.stale_count == 1


def test_fast_movers_are_never_stale():
    rows = [_cover_row(_P1, stock_on_hand=10, cover_days=Decimal("5"))]  # fast mover
    result = classify_stock_review({_P1: 10}, rows, [], {})
    assert result.stale_count == 0


def test_excess_flags_a_product_carrying_far_more_than_its_own_threshold():
    threshold = Decimal("7")
    rows = [_cover_row(_P1, stock_on_hand=100, cover_days=threshold * EXCESS_STOCK_COVER_MULTIPLIER)]
    result = classify_stock_review({_P1: 100}, rows, [], {_P1: threshold})
    assert result.excess_count == 1


def test_excess_not_flagged_when_cover_is_close_to_threshold():
    threshold = Decimal("7")
    rows = [_cover_row(_P1, stock_on_hand=20, cover_days=threshold * 2)]  # under the 3x multiplier
    result = classify_stock_review({_P1: 20}, rows, [], {_P1: threshold})
    assert result.excess_count == 0


def test_excess_never_flagged_without_a_known_cover_days():
    """"Do not classify items when evidence is incomplete" — a product
    with no real recent sales to estimate cover from (cover_days=None,
    the dead-stock case) is never called "excess" either, even with a
    huge stock count."""
    rows = [_cover_row(_P1, stock_on_hand=10_000, cover_days=None)]
    result = classify_stock_review({_P1: 10_000}, rows, [], {_P1: Decimal("7")})
    assert result.excess_count == 0


def test_excess_never_flagged_without_a_known_threshold():
    rows = [_cover_row(_P1, stock_on_hand=100, cover_days=Decimal("500"))]
    result = classify_stock_review({_P1: 100}, rows, [], {})  # no threshold on record
    assert result.excess_count == 0


def test_a_product_can_be_both_stale_and_excess():
    threshold = Decimal("7")
    rows = [_cover_row(_P1, stock_on_hand=100, cover_days=Decimal("90"))]  # slow mover AND >= 3x threshold
    result = classify_stock_review({_P1: 100}, rows, [], {_P1: threshold})
    assert result.stale_count == 1
    assert result.excess_count == 1


def test_everything_zero_when_nothing_to_flag():
    rows = [_cover_row(_P1, stock_on_hand=10, cover_days=Decimal("5"))]
    result = classify_stock_review({_P1: 10}, rows, [], {_P1: Decimal("7")})
    assert result.out_of_stock_count == 0
    assert result.stale_count == 0
    assert result.excess_count == 0
