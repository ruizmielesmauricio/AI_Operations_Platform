from datetime import date, timedelta
from decimal import Decimal

from app.analytics.forecasting import (
    MAX_LOOKBACK_DAYS,
    MIN_DAYS_FOR_SEASONAL,
    MIN_HISTORY_DAYS,
    compute_baseline_forecast,
)

_TODAY = date(2026, 3, 16)  # a Monday


def _window(days: int, value_fn) -> dict[date, Decimal]:
    """Builds a `days`-long window of business-local dates ending the day
    before _TODAY, one Decimal value per day via value_fn(d)."""
    return {_TODAY - timedelta(days=offset): value_fn(_TODAY - timedelta(days=offset)) for offset in range(1, days + 1)}


def test_below_minimum_history_is_insufficient_data():
    daily = _window(MIN_HISTORY_DAYS - 1, lambda d: Decimal("50"))
    result = compute_baseline_forecast(daily, horizon_days=7, today=_TODAY)

    assert result.insufficient_data is True
    assert result.method is None
    assert result.daily == []
    assert result.total_point == Decimal("0")


def test_at_minimum_history_produces_a_forecast():
    daily = _window(MIN_HISTORY_DAYS, lambda d: Decimal("50"))
    result = compute_baseline_forecast(daily, horizon_days=1, today=_TODAY)

    assert result.insufficient_data is False
    assert result.history_days_used == MIN_HISTORY_DAYS


def test_below_seasonal_threshold_uses_moving_average_with_hand_computed_variance():
    # 13 days at 10, 1 day at 24 -> mean = 154/14 = 11 exactly.
    # sample variance = ((13 * (10-11)**2) + (1 * (24-11)**2)) / (14 - 1)
    #                 = (13 * 1 + 1 * 169) / 13 = 182 / 13 = 14 exactly.
    values = [Decimal("10")] * 13 + [Decimal("24")]
    days = [_TODAY - timedelta(days=offset) for offset in range(1, MIN_HISTORY_DAYS + 1)]
    assert len(days) == 14
    daily = dict(zip(days, values))

    result = compute_baseline_forecast(daily, horizon_days=3, today=_TODAY)

    assert result.method == "moving_average"
    assert result.history_days_used == 14
    expected_std = Decimal(14).sqrt()
    for day in result.daily:
        assert day.point == Decimal("11")
        assert day.low == Decimal("11") - expected_std
        assert day.high == Decimal("11") + expected_std
    # Moving average repeats the same point for every forecast day.
    assert len({d.point for d in result.daily}) == 1
    assert result.total_point == Decimal("33")  # 11 * 3 days


def test_at_seasonal_threshold_uses_day_of_week_seasonality():
    # 3 full weeks (21 days): every Saturday is 100, every other day is 10.
    # A flat moving average over the same data would be
    # (18*10 + 3*100) / 21 = 480/21 ≈ 22.857 — neither 10 nor 100 — so a
    # seasonal forecast landing exactly on 10/100 proves it's genuinely
    # using the day-of-week pattern, not just falling back to the average.
    def value_fn(d: date) -> Decimal:
        return Decimal("100") if d.weekday() == 5 else Decimal("10")  # 5 = Saturday

    daily = _window(MIN_DAYS_FOR_SEASONAL, value_fn)
    result = compute_baseline_forecast(daily, horizon_days=7, today=_TODAY)

    assert result.method == "seasonal_day_of_week"
    assert result.history_days_used == MIN_DAYS_FOR_SEASONAL

    by_weekday = {d.forecast_date.weekday(): d for d in result.daily}
    assert by_weekday[5].point == Decimal("100")  # Saturday
    assert by_weekday[5].low == Decimal("100")  # zero variance — every historical Saturday was identical
    assert by_weekday[5].high == Decimal("100")
    for weekday, forecast in by_weekday.items():
        if weekday != 5:
            assert forecast.point == Decimal("10")
            assert forecast.low == Decimal("10")
            assert forecast.high == Decimal("10")

    flat_moving_average = Decimal("480") / Decimal("21")
    assert by_weekday[5].point != flat_moving_average
    assert by_weekday[0].point != flat_moving_average


def test_lookback_window_is_capped_at_max_lookback_days():
    # One very old, extreme-value day sits just outside the 90-day cap —
    # if it leaked into the average, every forecast day would be skewed
    # far above 10.
    daily = _window(MAX_LOOKBACK_DAYS, lambda d: Decimal("10"))
    daily[_TODAY - timedelta(days=MAX_LOOKBACK_DAYS + 1)] = Decimal("1000000")

    result = compute_baseline_forecast(daily, horizon_days=1, today=_TODAY)

    assert result.history_days_used == MAX_LOOKBACK_DAYS
    assert result.daily[0].point == Decimal("10")


def test_all_zero_history_forecasts_zero_with_no_negative_low():
    daily = _window(MIN_HISTORY_DAYS, lambda d: Decimal("0"))
    result = compute_baseline_forecast(daily, horizon_days=2, today=_TODAY)

    assert result.insufficient_data is False
    for day in result.daily:
        assert day.point == Decimal("0")
        assert day.low == Decimal("0")
        assert day.high == Decimal("0")
    assert result.total_point == Decimal("0")
    assert result.total_low == Decimal("0")
    assert result.total_high == Decimal("0")


def test_low_is_floored_at_zero_even_when_point_minus_std_would_go_negative():
    # 13 days at 0, one day at a big spike -> high variance relative to a
    # low mean, so point - std goes negative; low must clamp to 0, not a
    # nonsensical negative amount/count.
    values = [Decimal("0")] * 13 + [Decimal("100")]
    days = [_TODAY - timedelta(days=offset) for offset in range(1, 15)]
    daily = dict(zip(days, values))

    result = compute_baseline_forecast(daily, horizon_days=1, today=_TODAY)

    assert result.daily[0].point > Decimal("0")
    assert result.daily[0].low == Decimal("0")
    assert result.total_low == Decimal("0")


def test_total_is_sum_of_daily_points_and_variance_adds_before_sqrt():
    # Moving-average path: every day has the same point/variance, so the
    # total's std should be sqrt(horizon_days * daily_variance), not
    # horizon_days * daily_std (variances add under independence, not
    # standard deviations).
    values = [Decimal("10")] * 13 + [Decimal("24")]  # same fixture as the hand-computed variance test: variance = 14
    days = [_TODAY - timedelta(days=offset) for offset in range(1, 15)]
    daily = dict(zip(days, values))

    horizon_days = 4
    result = compute_baseline_forecast(daily, horizon_days=horizon_days, today=_TODAY)

    expected_total_std = (Decimal(14) * horizon_days).sqrt()
    assert result.total_point == Decimal("11") * horizon_days
    assert result.total_high == result.total_point + expected_total_std
    assert result.total_low == result.total_point - expected_total_std
