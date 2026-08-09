"""C11's Workshop Performance addition — verifies
ProductionEventRepository.aggregate_completed_repairs_in_range and
get_workshop_performance against a real (SQLite) database, since the unit
tests in tests/unit/test_workshop_analytics.py exercise the pure formula
with hand-built totals and can't catch a wrong SQL aggregate on their own.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.workshop_performance import get_workshop_performance
from app.models.production_event import ProductionEvent
from app.repositories.production_event import ProductionEventRepository

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 7)  # inclusive, GMT (Dublin, no DST in January)


def _make_repair(
    db_session, business_id, *, completed_at, price_charged, labour_cost, status="completed", tax_amount=None
):
    db_session.add(
        ProductionEvent(
            business_id=business_id,
            event_type="repair",
            description="Brake adjustment",
            status=status,
            opened_at=completed_at,
            completed_at=completed_at,
            price_charged=price_charged,
            labour_cost=labour_cost,
            tax_amount=tax_amount,
        )
    )
    db_session.flush()


def _seed(db_session, business_id):
    # In-period, fully known.
    _make_repair(
        db_session,
        business_id,
        completed_at=datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc),
        price_charged=Decimal("80.00"),
        labour_cost=Decimal("30.00"),
    )
    # In-period, no labour cost recorded.
    _make_repair(
        db_session,
        business_id,
        completed_at=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
        price_charged=Decimal("50.00"),
        labour_cost=None,
    )
    # Out-of-period — must not be counted.
    _make_repair(
        db_session,
        business_id,
        completed_at=datetime(2025, 12, 20, 10, 0, tzinfo=timezone.utc),
        price_charged=Decimal("999.00"),
        labour_cost=Decimal("10.00"),
    )
    # Still open (not completed) — must not be counted even though it falls
    # in the date range.
    _make_repair(
        db_session,
        business_id,
        completed_at=datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc),
        price_charged=Decimal("500.00"),
        labour_cost=Decimal("50.00"),
        status="open",
    )
    db_session.commit()


def test_aggregate_completed_repairs_in_range_excludes_open_and_out_of_period(db_session, business_id):
    _seed(db_session, business_id)

    totals = ProductionEventRepository(db_session).aggregate_completed_repairs_in_range(
        business_id,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert totals.repair_count == 2
    assert totals.repairs_with_known_price == 2
    assert totals.revenue == Decimal("130.00")
    assert totals.repairs_with_known_price_and_labour == 1
    assert totals.labour_cost_known_revenue == Decimal("80.00")
    assert totals.labour_cost == Decimal("30.00")


def test_get_workshop_performance_end_to_end(db_session, business_id):
    _seed(db_session, business_id)

    summary = get_workshop_performance(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END
    )

    assert summary.revenue.current == Decimal("130.00")
    assert summary.revenue.previous == Decimal("0.00")  # nothing in the prior 7-day window
    assert summary.margin.repair_count == 2
    assert summary.margin.gross_profit == Decimal("50.00")
    assert summary.margin.gross_margin_pct == Decimal("62.5")
    assert summary.margin.labour_cost_coverage_pct == Decimal("61.5")
    assert summary.margin.average_ticket == Decimal("65.00")


def test_aggregate_with_no_repairs_in_range_returns_zeroed_totals(db_session, business_id):
    totals = ProductionEventRepository(db_session).aggregate_completed_repairs_in_range(
        business_id,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert totals.repair_count == 0
    assert totals.revenue == Decimal("0")


def test_aggregate_and_end_to_end_compute_net_of_tax_from_a_real_repair_row(db_session, business_id):
    # Real DB round-trip for the tax-inclusive margin fix — the unit tests
    # in test_workshop_analytics.py exercise compute_workshop_margin with
    # hand-built totals; this proves the SQL aggregate (known_both_and_tax
    # in ProductionEventRepository.aggregate_completed_repairs_in_range)
    # correctly derives those totals from actual rows, tax-known and
    # tax-unknown side by side.
    _make_repair(
        db_session,
        business_id,
        completed_at=datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc),
        price_charged=Decimal("80.00"),  # tax-inclusive: 10.00 of this is tax
        labour_cost=Decimal("30.00"),
        tax_amount=Decimal("10.00"),
    )
    _make_repair(
        db_session,
        business_id,
        completed_at=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
        price_charged=Decimal("50.00"),  # known price/labour, tax not recorded
        labour_cost=Decimal("20.00"),
        tax_amount=None,
    )
    db_session.commit()

    totals = ProductionEventRepository(db_session).aggregate_completed_repairs_in_range(
        business_id,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 8, tzinfo=timezone.utc),
    )
    assert totals.labour_cost_known_revenue_with_known_tax == Decimal("80.00")
    assert totals.tax_amount_known == Decimal("10.00")
    assert totals.labour_cost_for_known_tax == Decimal("30.00")

    summary = get_workshop_performance(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END
    )
    # gross_margin_pct (tax-inclusive, both repairs): (130-50)/130 = 61.5%
    assert summary.margin.gross_margin_pct == Decimal("61.5")
    # net_gross_margin_pct (only the tax-known repair): (80-10-30)/(80-10) = 57.1%
    assert summary.margin.net_gross_profit == Decimal("40.00")
    assert summary.margin.net_gross_margin_pct == Decimal("57.1")
    assert summary.margin.tax_data_coverage_pct == Decimal("61.5")  # 80 / 130
