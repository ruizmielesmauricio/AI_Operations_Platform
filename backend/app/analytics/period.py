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
