from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.analytics.period import (
    MetricPeriod,
    compute_report_period,
    group_amounts_by_local_date,
    is_report_period_due,
    resolve_period,
)


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


# --- compute_report_period (Stage D17/D18) --------------------------------


def test_weekly_report_period_covers_the_previous_completed_week():
    # 2026-08-06 is a Thursday; the most recent Monday is 2026-08-03.
    now = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
    start, end = compute_report_period("UTC", "weekly", now=now)
    assert start == date(2026, 7, 27)
    assert end == date(2026, 8, 2)


def test_weekly_report_period_on_a_monday_still_covers_last_week_not_this_one():
    now = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)  # a Monday
    start, end = compute_report_period("UTC", "weekly", now=now)
    assert start == date(2026, 7, 27)
    assert end == date(2026, 8, 2)


def test_monthly_report_period_covers_the_previous_calendar_month():
    now = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
    start, end = compute_report_period("UTC", "monthly", now=now)
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_monthly_report_period_on_the_1st_still_covers_last_month():
    now = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    start, end = compute_report_period("UTC", "monthly", now=now)
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 31)


def test_report_period_uses_business_local_date_not_utc():
    # 23:30 UTC on a Sunday is already Monday in Tokyo (fixed UTC+9) — the
    # weekly period boundary must follow the business's own calendar, not UTC's.
    now = datetime(2026, 8, 2, 23, 30, tzinfo=timezone.utc)  # Sunday in UTC, Monday in Tokyo
    start, end = compute_report_period("Asia/Tokyo", "weekly", now=now)
    assert start == date(2026, 7, 27)
    assert end == date(2026, 8, 2)


def test_report_period_rejects_an_unknown_report_type():
    with pytest.raises(ValueError):
        compute_report_period("UTC", "daily", now=datetime(2026, 8, 6, tzinfo=timezone.utc))


# --- is_report_period_due (Stage D17/D18) ---------------------------------


def test_period_is_not_due_before_generation_hour_on_the_transition_day():
    # Weekly period ends 2026-08-02 (Sunday) -> due Monday 2026-08-03 08:00.
    # 07:59 that Monday: not yet due.
    now = datetime(2026, 8, 3, 7, 59, tzinfo=timezone.utc)
    assert is_report_period_due("UTC", date(2026, 8, 2), now=now) is False


def test_period_is_due_exactly_at_the_generation_hour():
    now = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
    assert is_report_period_due("UTC", date(2026, 8, 2), now=now) is True


def test_period_stays_due_days_later_recovery_case():
    # The tick was down for a few days — must still recognize the period
    # as due once it eventually runs, not just on the exact generation day.
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    assert is_report_period_due("UTC", date(2026, 8, 2), now=now) is True


def test_period_due_check_uses_business_local_time_not_utc():
    # 2026-08-02 22:30 UTC is already 2026-08-03 07:30 in Tokyo (UTC+9) —
    # local generation hour (08:00) hasn't arrived yet even though the UTC
    # calendar date has already rolled to the 3rd.
    now = datetime(2026, 8, 2, 22, 30, tzinfo=timezone.utc)
    assert is_report_period_due("Asia/Tokyo", date(2026, 8, 2), now=now) is False

    later = datetime(2026, 8, 2, 23, 1, tzinfo=timezone.utc)  # 08:01 Tokyo time
    assert is_report_period_due("Asia/Tokyo", date(2026, 8, 2), now=later) is True


# --- Daylight saving & timezone boundaries (Dublin, Auckland) --------------
#
# Europe/Dublin 2026: clocks go forward Sun 29 Mar (01:00 UTC) and back Sun
# 25 Oct (01:00 UTC). Pacific/Auckland (southern hemisphere, opposite
# season): forward Sun 27 Sep (14:00 UTC the day before), back Sun 5 Apr.
# A local calendar week across a changeover is 167h or 169h, not 168h.

_DUBLIN = "Europe/Dublin"


def _hours(period) -> float:
    return (period.end - period.start).total_seconds() / 3600


def test_a_spring_forward_week_is_167_hours_but_still_7_days():
    # Real bug this guards: (end - start).days on UTC datetimes floored
    # 167h to 6 days, inflating every per-day figure (stock-cover average
    # daily demand) for that week by ~17%.
    period = resolve_period(_DUBLIN, date(2026, 3, 23), date(2026, 3, 29))
    assert _hours(period) == 167
    assert period.days == 7


def test_a_fall_back_week_is_169_hours_and_still_7_days():
    period = resolve_period(_DUBLIN, date(2026, 10, 19), date(2026, 10, 25))
    assert _hours(period) == 169
    assert period.days == 7


def test_a_month_containing_the_spring_changeover_still_counts_all_its_days():
    assert resolve_period(_DUBLIN, date(2026, 3, 1), date(2026, 3, 31)).days == 31


def test_a_month_containing_the_autumn_changeover_still_counts_all_its_days():
    assert resolve_period(_DUBLIN, date(2026, 10, 1), date(2026, 10, 31)).days == 31


def test_previous_week_after_spring_forward_lands_on_local_midnight_not_an_hour_off():
    # Week 30 Mar - 5 Apr (IST, UTC+1). The week before is 23-29 Mar, which
    # *starts* in GMT: local midnight Mon 23 Mar is 00:00 UTC. A fixed
    # 7x24h step back would land on 23:00 UTC the previous night, pulling
    # an extra hour of Sunday 22 Mar into last week's totals.
    period = resolve_period(_DUBLIN, date(2026, 3, 30), date(2026, 4, 5))
    previous = period.previous()
    assert previous.start == datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc)
    assert previous.end == period.start
    assert previous.days == 7


def test_previous_week_after_fall_back_lands_on_local_midnight():
    # Week 26 Oct - 1 Nov (GMT). The week before, 19-25 Oct, starts in IST
    # (UTC+1): local midnight Mon 19 Oct is 23:00 UTC on the 18th.
    period = resolve_period(_DUBLIN, date(2026, 10, 26), date(2026, 11, 1))
    previous = period.previous()
    assert previous.start == datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)
    assert previous.end == period.start
    assert previous.days == 7


def test_previous_period_still_tiles_across_a_changeover():
    period = resolve_period(_DUBLIN, date(2026, 3, 30), date(2026, 4, 5))
    assert period.previous().end == period.start


def test_a_period_built_without_a_timezone_falls_back_to_rounded_whole_days():
    naive = MetricPeriod(
        start=datetime(2026, 3, 22, 23, 0, tzinfo=timezone.utc), end=datetime(2026, 3, 29, 23, 0, tzinfo=timezone.utc)
    )
    assert naive.days == 7


def test_weekly_period_uses_the_local_monday_across_the_spring_changeover():
    # 23:30 UTC Sunday 29 Mar is already 00:30 Monday 30 Mar in Dublin
    # (IST) — the report period must follow the *local* calendar.
    now = datetime(2026, 3, 29, 23, 30, tzinfo=timezone.utc)
    assert compute_report_period(_DUBLIN, "weekly", now=now) == (date(2026, 3, 23), date(2026, 3, 29))


def test_weekly_period_is_unchanged_at_the_same_utc_instant_before_the_changeover_week():
    # Same UTC clock time the Sunday before the changeover: still GMT, still Sunday locally.
    now = datetime(2026, 3, 22, 23, 30, tzinfo=timezone.utc)
    assert compute_report_period(_DUBLIN, "weekly", now=now) == (date(2026, 3, 9), date(2026, 3, 15))


def test_monthly_period_across_the_changeover_months():
    assert compute_report_period(_DUBLIN, "monthly", now=datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc)) == (
        date(2026, 3, 1),
        date(2026, 3, 31),
    )
    assert compute_report_period(_DUBLIN, "monthly", now=datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
    )


def test_due_moment_after_the_spring_changeover_is_0700_utc():
    # Weekly period ends Sun 29 Mar -> due Mon 30 Mar 08:00 IST = 07:00 UTC.
    end = date(2026, 3, 29)
    assert is_report_period_due(_DUBLIN, end, now=datetime(2026, 3, 30, 6, 59, tzinfo=timezone.utc)) is False
    assert is_report_period_due(_DUBLIN, end, now=datetime(2026, 3, 30, 7, 0, tzinfo=timezone.utc)) is True


def test_due_moment_after_the_autumn_changeover_is_0800_utc_not_0700():
    # Weekly period ends Sun 25 Oct -> due Mon 26 Oct 08:00 GMT = 08:00 UTC.
    # 07:00 UTC would be 08:00 if summer time had persisted — must NOT be due.
    end = date(2026, 10, 25)
    assert is_report_period_due(_DUBLIN, end, now=datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)) is False
    assert is_report_period_due(_DUBLIN, end, now=datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)) is True


def test_monthly_due_moment_follows_local_time_in_both_changeover_months():
    # March ends 31st -> due 1 Apr 08:00 IST (07:00 UTC); October ends 31st -> due 1 Nov 08:00 GMT (08:00 UTC).
    assert is_report_period_due(_DUBLIN, date(2026, 3, 31), now=datetime(2026, 4, 1, 6, 59, tzinfo=timezone.utc)) is False
    assert is_report_period_due(_DUBLIN, date(2026, 3, 31), now=datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc)) is True
    assert is_report_period_due(_DUBLIN, date(2026, 10, 31), now=datetime(2026, 11, 1, 7, 59, tzinfo=timezone.utc)) is False
    assert is_report_period_due(_DUBLIN, date(2026, 10, 31), now=datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)) is True


def test_southern_hemisphere_changeover_due_moment_in_auckland():
    # NZ clocks go forward Sun 27 Sep 2026; weekly period ends that Sunday
    # -> due Mon 28 Sep 08:00 NZDT (UTC+13) = Sun 27 Sep 19:00 UTC — still
    # the *UTC Sunday*, a full day before the UTC date the Monday suggests.
    end = date(2026, 9, 27)
    assert is_report_period_due("Pacific/Auckland", end, now=datetime(2026, 9, 27, 18, 59, tzinfo=timezone.utc)) is False
    assert is_report_period_due("Pacific/Auckland", end, now=datetime(2026, 9, 27, 19, 0, tzinfo=timezone.utc)) is True


def test_auckland_period_days_across_its_own_changeover():
    period = resolve_period("Pacific/Auckland", date(2026, 9, 21), date(2026, 9, 27))
    assert _hours(period) == 167
    assert period.days == 7
