from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.period import group_amounts_by_local_date, resolve_period


def test_default_window_is_trailing_30_days_ending_today_in_business_timezone():
    # 2026-08-04 10:00 UTC is 2026-08-04 11:00 in Europe/Dublin (BST, UTC+1)
    # during summer — "today" should be the Dublin calendar date, not UTC's.
    now = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
    period = resolve_period("Europe/Dublin", None, None, now=now)

    assert period.end == datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc)
    assert period.start == period.end - timedelta(days=30)
    assert period.days == 30


def test_explicit_dates_are_interpreted_as_business_local_calendar_days():
    period = resolve_period("Europe/Dublin", date(2026, 7, 1), date(2026, 7, 7))

    # July in Dublin is BST (UTC+1): local midnight July 1 is 23:00 UTC June 30.
    assert period.start == datetime(2026, 6, 30, 23, 0, tzinfo=timezone.utc)
    # end_date is inclusive as a calendar day, so the exclusive UTC boundary
    # is midnight *after* July 7 in Dublin.
    assert period.end == datetime(2026, 7, 7, 23, 0, tzinfo=timezone.utc)
    assert period.days == 7


def test_timezone_crossing_utc_offset_zero_is_a_no_op():
    period = resolve_period("UTC", date(2026, 1, 1), date(2026, 1, 1))
    assert period.start == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert period.end == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert period.days == 1


def test_previous_period_is_equal_length_and_tiles_with_no_gap():
    period = resolve_period("UTC", date(2026, 1, 8), date(2026, 1, 14))
    previous = period.previous()

    assert previous.end == period.start
    assert (previous.end - previous.start) == (period.end - period.start)


# --- group_amounts_by_local_date (Stage C13) ------------------------------


def test_group_amounts_sums_rows_landing_on_the_same_local_date():
    rows = [
        (datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc), Decimal("10.00")),
        (datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc), Decimal("5.00")),
        (datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc), Decimal("3.00")),
    ]
    buckets = group_amounts_by_local_date(
        rows, "UTC", window_start=date(2026, 1, 5), window_end=date(2026, 1, 6)
    )
    assert buckets == {date(2026, 1, 5): Decimal("15.00"), date(2026, 1, 6): Decimal("3.00")}


def test_group_amounts_zero_fills_every_day_in_the_window_with_no_rows():
    buckets = group_amounts_by_local_date(
        [], "UTC", window_start=date(2026, 1, 1), window_end=date(2026, 1, 3)
    )
    assert buckets == {
        date(2026, 1, 1): Decimal("0"),
        date(2026, 1, 2): Decimal("0"),
        date(2026, 1, 3): Decimal("0"),
    }


def test_group_amounts_uses_business_local_calendar_date_not_utc():
    # 23:30 UTC on Jan 5 is 08:30 on Jan 6 in Tokyo (a fixed UTC+9, no DST)
    # — must bucket to the 6th, not the UTC date.
    rows = [(datetime(2026, 1, 5, 23, 30, tzinfo=timezone.utc), Decimal("7.00"))]
    buckets = group_amounts_by_local_date(
        rows, "Asia/Tokyo", window_start=date(2026, 1, 5), window_end=date(2026, 1, 6)
    )
    assert buckets[date(2026, 1, 5)] == Decimal("0")
    assert buckets[date(2026, 1, 6)] == Decimal("7.00")


def test_group_amounts_ignores_rows_outside_the_window():
    rows = [
        (datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), Decimal("100.00")),  # before window_start
        (datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc), Decimal("200.00")),  # after window_end
        (datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc), Decimal("3.00")),
    ]
    buckets = group_amounts_by_local_date(
        rows, "UTC", window_start=date(2026, 1, 5), window_end=date(2026, 1, 5)
    )
    assert buckets == {date(2026, 1, 5): Decimal("3.00")}
