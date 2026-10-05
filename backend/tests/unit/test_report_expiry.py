"""app/analytics/report_expiry.py — the server-side countdown behind the
"available for N more days" counter on weekly AND monthly reports (both
expire seven days after generation, ADR-019)."""

from datetime import datetime, timedelta, timezone

from app.analytics.report_expiry import EXPIRING_SOON_SECONDS, is_expiring_soon, seconds_until_expiry

_NOW = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


def test_a_fresh_report_has_seven_days_left():
    assert seconds_until_expiry(_NOW + timedelta(days=7), now=_NOW) == 7 * 24 * 3600


def test_remaining_time_counts_down_to_the_second():
    assert seconds_until_expiry(_NOW + timedelta(hours=5, minutes=30), now=_NOW) == 5 * 3600 + 30 * 60


def test_an_already_expired_report_reads_zero_never_negative():
    assert seconds_until_expiry(_NOW - timedelta(days=3), now=_NOW) == 0


def test_exactly_at_expiry_reads_zero():
    assert seconds_until_expiry(_NOW, now=_NOW) == 0


def test_no_expiry_means_no_countdown():
    assert seconds_until_expiry(None, now=_NOW) is None


def test_a_naive_datetime_is_treated_as_utc_like_sqlite_round_trips_it():
    naive = (_NOW + timedelta(days=1)).replace(tzinfo=None)
    assert seconds_until_expiry(naive, now=_NOW) == 24 * 3600


def test_expiring_soon_flips_at_the_two_day_threshold():
    assert is_expiring_soon(EXPIRING_SOON_SECONDS + 1) is False
    assert is_expiring_soon(EXPIRING_SOON_SECONDS) is True
    assert is_expiring_soon(0) is True


def test_a_report_with_no_countdown_is_never_expiring_soon():
    assert is_expiring_soon(None) is False
