"""Stage C13 — deterministic forecasting baseline (seasonal/moving
average). Pure — same conventions as every other module in this package:
plain Decimal inputs, no DB, no I/O, no AI (per CLAUDE.md's "Business
Logic First" — AI never calculates). Unit-tested directly in
tests/unit/test_forecasting.py.

One function, `compute_baseline_forecast`, is reused for both business-wide
revenue and per-product unit demand (app/application/forecast.py) — it
doesn't know or care what the Decimal values represent, only that they're
one value per calendar day.

Method: day-of-week seasonal naive when there's enough history to support
it, otherwise a plain moving average — literally "seasonal/moving average"
from the roadmap line, chosen deterministically by how much history
exists, never blended. Confidence range is the sample standard deviation
of the historical values feeding each forecast day (Decimal has a native
.sqrt(), so this never touches float). Below a stated minimum history, no
forecast is produced at all — a data-completeness gate, same philosophy as
GrossMarginResult's cost_data_coverage_pct and every other "don't invent
confidence that doesn't exist" flag in this codebase.

Known, stated limitation: only day-of-week seasonality is attempted.
Monthly/yearly seasonality (e.g. a genuine seasonal-demand cycle) would
need 1-2+ years of history no new pilot business will realistically have
yet — closing that gap is what Stage C14/C15's weather-signal augmentation
is for, not something this baseline should fake.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

# Below this many days of lookback history, no forecast is produced at
# all — better to say "not enough data yet" than to fabricate a number
# from a handful of days.
MIN_HISTORY_DAYS = 14

# At or above this many days of history, day-of-week seasonality can be
# estimated (each weekday will have appeared at least 3 times in any
# window this long) — below it but at/above MIN_HISTORY_DAYS, fall back to
# a plain moving average instead.
MIN_DAYS_FOR_SEASONAL = 21

# How far back the lookback window is allowed to reach, regardless of how
# much history actually exists — bounds query cost and keeps the average
# "recent" rather than dragging in old, possibly no-longer-representative
# history.
MAX_LOOKBACK_DAYS = 90

_SEASONAL = "seasonal_day_of_week"
_MOVING_AVERAGE = "moving_average"


@dataclass(frozen=True)
class DailyForecast:
    forecast_date: date
    point: Decimal
    # A "typical range" (± one sample standard deviation of the historical
    # values behind this day's estimate) — not a formal statistical
    # guarantee, just an honest sense of how much this day's value has
    # historically varied. low is floored at 0 (a negative amount/count
    # isn't a meaningful lower bound).
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class ForecastResult:
    # True when there's under MIN_HISTORY_DAYS of lookback history — every
    # other field is then meaningless and callers must not display them.
    insufficient_data: bool
    # Which method actually ran (None when insufficient_data). Surfaced so
    # a caller/UI can be honest about which baseline produced a number.
    method: str | None
    history_days_used: int
    daily: list[DailyForecast]
    total_point: Decimal
    total_low: Decimal
    total_high: Decimal


def _sample_variance(values: list[Decimal]) -> Decimal:
    """Unbiased sample variance (divide by n-1). A single value has no
    estimable spread — callers must guard against len(values) < 2
    themselves (compute_baseline_forecast's thresholds guarantee this)."""
    n = len(values)
    mean = sum(values) / n
    squared_diffs = sum((v - mean) ** 2 for v in values)
    return squared_diffs / (n - 1)


def compute_baseline_forecast(
    daily_values: dict[date, Decimal], horizon_days: int, *, today: date
) -> ForecastResult:
    """`daily_values` must have one entry for every calendar day in the
    lookback window (zero-filled for no-activity days by the caller —
    app/analytics/period.py's group_amounts_by_local_date does this) and
    cover only days strictly before `today` (forecasting only ever looks
    forward; a partial "today" would bias the average low). `horizon_days`
    is how many future days (starting today) to forecast.
    """
    history_days_used = min(len(daily_values), MAX_LOOKBACK_DAYS)
    if history_days_used < MIN_HISTORY_DAYS:
        return ForecastResult(
            insufficient_data=True,
            method=None,
            history_days_used=history_days_used,
            daily=[],
            total_point=Decimal("0"),
            total_low=Decimal("0"),
            total_high=Decimal("0"),
        )

    # Only the most recent MAX_LOOKBACK_DAYS days count, even if more
    # history exists — keeps the average bounded and recent.
    window_start = today - timedelta(days=history_days_used)
    window = {d: v for d, v in daily_values.items() if window_start <= d < today}

    use_seasonal = history_days_used >= MIN_DAYS_FOR_SEASONAL
    method = _SEASONAL if use_seasonal else _MOVING_AVERAGE

    if use_seasonal:
        by_weekday: dict[int, list[Decimal]] = {}
        for d, v in window.items():
            by_weekday.setdefault(d.weekday(), []).append(v)
    else:
        all_values = list(window.values())

    daily: list[DailyForecast] = []
    total_point = Decimal("0")
    total_variance = Decimal("0")
    for offset in range(horizon_days):
        forecast_date = today + timedelta(days=offset)
        values = by_weekday[forecast_date.weekday()] if use_seasonal else all_values
        point = sum(values) / len(values)
        variance = _sample_variance(values) if len(values) >= 2 else Decimal("0")
        std = variance.sqrt()
        daily.append(DailyForecast(forecast_date=forecast_date, point=point, low=max(Decimal("0"), point - std), high=point + std))
        total_point += point
        total_variance += variance

    total_std = total_variance.sqrt()
    return ForecastResult(
        insufficient_data=False,
        method=method,
        history_days_used=history_days_used,
        daily=daily,
        total_point=total_point,
        total_low=max(Decimal("0"), total_point - total_std),
        total_high=total_point + total_std,
    )
