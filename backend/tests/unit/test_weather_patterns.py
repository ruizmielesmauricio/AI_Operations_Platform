import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.analytics.weather_patterns import (
    BUCKETS,
    COLD,
    MILD_DRY,
    MIN_BUCKET_DAYS,
    RAINY,
    WINDY,
    DailyWeather,
    classify_day,
    classify_upcoming_buckets,
    compute_weather_pattern_comparison,
)

_CATEGORY_A = uuid.uuid4()
_CATEGORY_B = uuid.uuid4()


def _weather(day: date, *, rain=Decimal("0"), temp=Decimal("15"), wind=Decimal("10")) -> DailyWeather:
    return DailyWeather(day=day, rain_mm=rain, temp_mean_c=temp, wind_speed_kph=wind)


def test_classify_day_matches_rainy_cold_windy_independently():
    day = date(2026, 1, 1)
    assert classify_day(_weather(day, rain=Decimal("5"))) == frozenset({RAINY})
    assert classify_day(_weather(day, temp=Decimal("3"))) == frozenset({COLD})
    assert classify_day(_weather(day, wind=Decimal("40"))) == frozenset({WINDY})


def test_classify_day_can_match_more_than_one_bucket():
    day = date(2026, 1, 1)
    result = classify_day(_weather(day, rain=Decimal("5"), temp=Decimal("2")))
    assert result == frozenset({RAINY, COLD})


def test_classify_day_mild_dry_is_unremarkable_good_weather():
    day = date(2026, 1, 1)
    assert classify_day(_weather(day, rain=Decimal("0"), temp=Decimal("18"), wind=Decimal("5"))) == frozenset(
        {MILD_DRY}
    )
    # Just outside the mild range on temperature alone -> no bucket at all,
    # not silently pushed into an adjacent one.
    assert classify_day(_weather(day, rain=Decimal("0"), temp=Decimal("25"), wind=Decimal("5"))) == frozenset()


def test_classify_day_trace_rain_below_threshold_is_not_rainy():
    day = date(2026, 1, 1)
    assert RAINY not in classify_day(_weather(day, rain=Decimal("0.3")))


def _build_history(rainy_days: int, other_days: int, *, rainy_units: Decimal, other_units: Decimal):
    """MIN_BUCKET_DAYS rainy days at `rainy_units`/day, `other_days` dry
    days at `other_units`/day — hand-computable averages by construction.
    """
    start = date(2026, 1, 1)
    daily_weather: dict[date, DailyWeather] = {}
    daily_units: dict[date, Decimal] = {}
    d = start
    for _ in range(rainy_days):
        daily_weather[d] = _weather(d, rain=Decimal("5"), temp=Decimal("15"))
        daily_units[d] = rainy_units
        d += timedelta(days=1)
    for _ in range(other_days):
        daily_weather[d] = _weather(d, rain=Decimal("0"), temp=Decimal("15"))
        daily_units[d] = other_units
        d += timedelta(days=1)
    return daily_weather, daily_units


def test_below_min_bucket_days_produces_no_comparison():
    daily_weather, daily_units = _build_history(
        MIN_BUCKET_DAYS - 1, 30, rainy_units=Decimal("10"), other_units=Decimal("2")
    )
    results = compute_weather_pattern_comparison(
        daily_weather, {_CATEGORY_A: daily_units}, {_CATEGORY_A: "Waterproof Gear"}
    )
    # Specifically the rainy bucket, which has too few real matching days
    # (MIN_BUCKET_DAYS - 1) -- the fixture's dry days happen to also
    # qualify as mild_dry with plenty of history, which is a separate,
    # legitimately-reportable comparison and not what this test checks.
    assert [r for r in results if r.bucket == RAINY] == []


def test_at_min_bucket_days_with_a_real_material_difference_produces_a_comparison():
    daily_weather, daily_units = _build_history(
        MIN_BUCKET_DAYS, 30, rainy_units=Decimal("10"), other_units=Decimal("2")
    )
    results = compute_weather_pattern_comparison(
        daily_weather, {_CATEGORY_A: daily_units}, {_CATEGORY_A: "Waterproof Gear"}
    )

    rainy_results = [r for r in results if r.bucket == RAINY]
    assert len(rainy_results) == 1
    result = rainy_results[0]
    assert result.category_id == _CATEGORY_A
    assert result.category_name == "Waterproof Gear"
    assert result.bucket_day_count == MIN_BUCKET_DAYS
    assert result.other_day_count == 30
    assert result.avg_on_bucket_days == Decimal("10")
    assert result.avg_on_other_days == Decimal("2")
    # (10 - 2) / 2 * 100 = 400% -- hand-computable, exact.
    assert result.pct_difference == Decimal("400")


def test_below_materiality_threshold_is_not_reported_even_with_enough_days():
    # 2.1 vs 2.0 -> 5% difference, real but tiny -- below the default 15%
    # materiality gate, must not be reported as a pattern.
    daily_weather, daily_units = _build_history(
        MIN_BUCKET_DAYS, 30, rainy_units=Decimal("2.1"), other_units=Decimal("2.0")
    )
    results = compute_weather_pattern_comparison(
        daily_weather, {_CATEGORY_A: daily_units}, {_CATEGORY_A: "Waterproof Gear"}
    )
    assert results == []


def test_zero_baseline_average_is_never_reported_as_a_percentage():
    # Category never sells at all on non-rainy days -- a % difference
    # from a zero baseline is undefined, must be skipped, not reported as
    # a fabricated "infinite% more."
    daily_weather, daily_units = _build_history(
        MIN_BUCKET_DAYS, 30, rainy_units=Decimal("5"), other_units=Decimal("0")
    )
    results = compute_weather_pattern_comparison(
        daily_weather, {_CATEGORY_A: daily_units}, {_CATEGORY_A: "Waterproof Gear"}
    )
    # Specifically the rainy bucket's own baseline (avg on the *other*,
    # non-rainy days) being zero -- the mild_dry bucket's baseline (avg on
    # the rainy days) is a real, non-zero, legitimately-reportable number
    # and isn't what this test checks.
    assert [r for r in results if r.bucket == RAINY] == []


def test_a_lower_sales_pattern_produces_a_negative_pct_difference():
    daily_weather, daily_units = _build_history(
        MIN_BUCKET_DAYS, 30, rainy_units=Decimal("1"), other_units=Decimal("5")
    )
    results = compute_weather_pattern_comparison(
        daily_weather, {_CATEGORY_A: daily_units}, {_CATEGORY_A: "Bicycles"}
    )
    rainy_results = [r for r in results if r.bucket == RAINY]
    assert len(rainy_results) == 1
    # (1 - 5) / 5 * 100 = -80%
    assert rainy_results[0].pct_difference == Decimal("-80")


def test_only_days_present_in_both_weather_and_sales_history_are_used():
    # Weather history starts later than sales history -- only the
    # overlapping days should ever be compared, never a synthetic
    # zero-fill for the gap.
    start = date(2026, 1, 1)
    daily_units = {start + timedelta(days=i): Decimal("3") for i in range(60)}
    # Weather only exists for the last 25 of those 60 days.
    daily_weather = {
        start + timedelta(days=i): _weather(start + timedelta(days=i), rain=Decimal("5") if i % 2 == 0 else Decimal("0"))
        for i in range(35, 60)
    }
    results = compute_weather_pattern_comparison(
        daily_weather, {_CATEGORY_A: daily_units}, {_CATEGORY_A: "Bicycles"}
    )
    # Flat 3 units/day regardless of weather -> no material difference to report,
    # but this must not raise or silently invent days outside the 25-day overlap.
    assert results == []


def test_different_categories_are_compared_independently():
    daily_weather, rainy_high_units = _build_history(
        MIN_BUCKET_DAYS, 30, rainy_units=Decimal("10"), other_units=Decimal("2")
    )
    # Reuse the same weather/date structure for a second category with a
    # flat, unremarkable sales pattern.
    flat_units = {d: Decimal("4") for d in daily_weather}
    results = compute_weather_pattern_comparison(
        daily_weather,
        {_CATEGORY_A: rainy_high_units, _CATEGORY_B: flat_units},
        {_CATEGORY_A: "Waterproof Gear", _CATEGORY_B: "Bicycles"},
    )
    category_ids_reported = {r.category_id for r in results}
    assert _CATEGORY_A in category_ids_reported
    assert _CATEGORY_B not in category_ids_reported


def test_classify_upcoming_buckets_needs_a_real_majority_not_one_day():
    start = date(2026, 3, 1)
    forecast = [_weather(start + timedelta(days=i), rain=Decimal("0")) for i in range(7)]
    forecast[0] = _weather(start, rain=Decimal("5"))  # only one rainy day out of seven
    assert RAINY not in classify_upcoming_buckets(forecast)


def test_classify_upcoming_buckets_matches_when_enough_days_qualify():
    start = date(2026, 3, 1)
    forecast = [_weather(start + timedelta(days=i), rain=Decimal("5")) for i in range(4)]
    forecast += [_weather(start + timedelta(days=i), rain=Decimal("0")) for i in range(4, 7)]
    assert RAINY in classify_upcoming_buckets(forecast)


def test_all_bucket_names_are_stable_strings_for_evidence_serialization():
    # Findings evidence (app/application/weather_insights.py) stores the
    # bucket label directly -- these must stay plain, stable strings, not
    # an enum whose repr could change.
    assert BUCKETS == ("rainy", "cold", "windy", "mild_dry")
