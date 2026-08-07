"""Reporting-period math shared by every Retail/Financial metric. Pure —
no DB, no FastAPI — so the date-boundary logic is unit-testable on its own
(ED-007) independent of any query that later uses it.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class MetricPeriod:
    """A half-open UTC range: [start, end). `end` exclusive so a period's
    `previous()` tiles exactly against it with no gap or overlap."""

    start: datetime
    end: datetime

    @property
    def days(self) -> int:
        # Whole days only — callers build periods from whole calendar days
        # (see resolve_period), so this is always an exact division.
        return (self.end - self.start).days

    def previous(self) -> "MetricPeriod":
        """The immediately preceding period of equal length, for trend
        comparison (e.g. this week vs last week)."""
        span = self.end - self.start
        return MetricPeriod(start=self.start - span, end=self.start)


def resolve_period(
    business_timezone: str,
    start_date: date | None,
    end_date: date | None,
    *,
    default_window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> MetricPeriod:
    """Turns an optional (start_date, end_date) pair of local calendar dates
    into a UTC MetricPeriod.

    Both dates are interpreted as *business-local* calendar days (per
    CLAUDE.md: "UTC internally, business timezone in settings") — a
    calendar day boundary in Dublin is not midnight UTC, so the conversion
    has to go through the business's own timezone rather than treating the
    dates as already-UTC.

    Missing dates default to the trailing `default_window_days` days ending
    "today" in the business's timezone. `now` is an injectable override
    (defaults to real wall-clock time) so callers can test this
    deterministically.
    """
    tz = ZoneInfo(business_timezone)
    current_time = now.astimezone(tz) if now is not None else datetime.now(tz)
    today = current_time.date()

    resolved_end_date = end_date if end_date is not None else today
    # end_date is inclusive, so a default_window_days-day window ending on
    # it starts default_window_days - 1 days earlier (e.g. a 30-day window
    # ending today includes today as one of the 30 days, not a 31st).
    resolved_start_date = (
        start_date if start_date is not None else resolved_end_date - timedelta(days=default_window_days - 1)
    )

    # end_date is the last *included* day, so the exclusive UTC boundary is
    # midnight at the start of the day after it.
    start_local = datetime.combine(resolved_start_date, time.min, tzinfo=tz)
    end_local = datetime.combine(resolved_end_date + timedelta(days=1), time.min, tzinfo=tz)

    return MetricPeriod(start=start_local.astimezone(timezone.utc), end=end_local.astimezone(timezone.utc))


def group_amounts_by_local_date(
    rows: list[tuple[datetime, Decimal]],
    business_timezone: str,
    *,
    window_start: date,
    window_end: date,
) -> dict[date, Decimal]:
    """Buckets UTC-timestamped (timestamp, amount) rows into business-local
    calendar days and sums each bucket — used by Stage C13's forecasting
    (app/analytics/forecasting.py) to turn raw sale/sale_item rows into the
    one-value-per-day series it needs.

    Every date in [window_start, window_end] (inclusive both ends) is
    present in the result, zero-filled if no row fell on it — a quiet day
    is a real zero data point for a moving average, not a missing one;
    silently dropping it would bias the average upward. Rows outside the
    window are ignored (callers are expected to have already queried a
    matching range, but this stays defensive rather than assuming it).
    """
    tz = ZoneInfo(business_timezone)
    buckets: dict[date, Decimal] = {}
    d = window_start
    while d <= window_end:
        buckets[d] = Decimal("0")
        d += timedelta(days=1)

    for timestamp, amount in rows:
        local_date = timestamp.astimezone(tz).date()
        if window_start <= local_date <= window_end:
            buckets[local_date] += amount

    return buckets


def compute_report_period(
    business_timezone: str, report_type: str, *, now: datetime | None = None
) -> tuple[date, date]:
    """Stage D17/D18 (PR-8.1/8.2): the most recently *completed* reporting
    period as of "now", as business-local calendar dates. Shared by
    app/application/report.py (generation) and app/scheduler/tick.py
    (deciding what's due) — both need exactly the same answer to the
    question "which period does the next weekly/monthly report cover."

    Weekly: the 7 days ending the day before the most recent Monday (i.e.
    last Monday through last Sunday, inclusive) — PR-8.1's "covers the
    previous completed week."
    Monthly: the full previous calendar month — PR-8.2's "covers the
    previous completed calendar month."
    """
    tz = ZoneInfo(business_timezone)
    today = (now.astimezone(tz) if now is not None else datetime.now(tz)).date()

    if report_type == "weekly":
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)
        end = this_monday - timedelta(days=1)
        return start, end
    if report_type == "monthly":
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timedelta(days=1)
        start = end.replace(day=1)
        return start, end
    raise ValueError(f"Unknown report_type: {report_type!r}")


# The hour (business-local) weekly/monthly reports become due, per
# PR-8.1/8.2's "every Monday at 08:00" / "the first calendar day at 08:00".
REPORT_GENERATION_HOUR = 8


def is_report_period_due(business_timezone: str, period_end_date: date, *, now: datetime) -> bool:
    """True once "now" is at or after the period's own generation moment —
    08:00 local on the calendar day immediately after period_end_date
    (the Monday after a weekly period's last Sunday; the 1st after a
    monthly period's last day). Not just "any time after the period
    ends": PR-8.1/8.2 specify a time of day, not just a date. Forgiving of
    exactly *how far* past that moment "now" is — a tick running hours or
    days late (after downtime) still returns True, which is what makes
    missed-report recovery (PR-8.10) automatic rather than needing a
    separate mechanism from generation itself.
    """
    tz = ZoneInfo(business_timezone)
    local_now = now.astimezone(tz)
    generation_date = period_end_date + timedelta(days=1)
    generation_moment = datetime.combine(generation_date, time(REPORT_GENERATION_HOUR, 0), tzinfo=tz)
    return local_now >= generation_moment
