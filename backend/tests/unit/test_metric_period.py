from datetime import date, datetime, timedelta, timezone

from app.analytics.period import resolve_period


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
