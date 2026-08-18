"""Deterministic weather-pattern sales insight — not ML, not a forecast.
Classifies days into a small, fixed, auditable taxonomy (every
classification is one threshold comparison, nothing learned) and compares
a business's own real historical sales by bucket. Pure — no DB, no I/O, no
AI, same layering as every other module in this package (CLAUDE.md's
"Business Logic First").

Direct product decision this exists at all: a weather-enhanced ML point-
forecast model was assessed and found not to hold up (see
docs/governance/11_Development_Roadmap.md v1.80) — this is the redirected
design. It never touches the deterministic forecast/reorder numbers in
app/analytics/forecasting.py at all; it only ever produces an additional,
separately-gated Finding.

Compliance boundary, direct instruction: nothing computed here (or
anything built on top of it) may surface a Met Éireann figure itself
(no raw rain-mm/temp-C/wind-kph value reaching a user-facing surface).
Only the bucket *label* below (ORLA's own classification, not Met
Éireann's data) and the business's own real sales numbers are meant to
ever leave this module's callers.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# A small, fixed taxonomy — deliberately not a continuous/learned
# embedding, so every classification is auditable by inspecting one
# threshold. A day can match more than one bucket (rainy and cold at
# once) or none at all.
RAINY = "rainy"
COLD = "cold"
WINDY = "windy"
MILD_DRY = "mild_dry"
BUCKETS: tuple[str, ...] = (RAINY, COLD, WINDY, MILD_DRY)

# >=1mm is the standard meteorological "wet day" threshold — a trace
# amount (0.1-0.9mm) is common and not what a shopkeeper would call
# "a rainy day."
_RAINY_MM = Decimal("1.0")
_COLD_C = Decimal("8")
_WINDY_KPH = Decimal("30")
_MILD_MIN_C = Decimal("12")
_MILD_MAX_C = Decimal("22")

# Below this many days actually falling in a bucket, refuse to compare at
# all — same "don't invent a pattern from a handful of days" philosophy
# as app/analytics/forecasting.py's own MIN_HISTORY_DAYS gate.
MIN_BUCKET_DAYS = 10

# A materiality gate on top of the sample-size gate — don't surface a 3%
# wobble as if it were a real pattern. Mirrors the general "don't flag
# noise" posture already used elsewhere in this codebase (e.g. the
# findings engine's own fixed percentage thresholds).
DEFAULT_MIN_PCT_DIFFERENCE = Decimal("15")

# How many of the next N forecast days need to match a bucket before it
# counts as "the upcoming week looks like X" — one rainy day out of seven
# shouldn't trigger an insight framed around "conditions this week."
DEFAULT_MIN_UPCOMING_MATCHING_DAYS = 3


@dataclass(frozen=True)
class DailyWeather:
    """One calendar day's aggregated weather — either an observed/near-
    real-time snapshot (app/application/weather_ingestion.py) or one day
    of a forward forecast (app/weather/client.py). Same shape either way,
    which is exactly what lets classify_day/compute_weather_pattern_
    comparison treat historical and upcoming days identically.
    """

    day: date
    rain_mm: Decimal
    temp_mean_c: Decimal
    wind_speed_kph: Decimal


def classify_day(weather: DailyWeather) -> frozenset[str]:
    """Every bucket the day matches — zero, one, or several. `mild_dry`
    is deliberately mutually exclusive with the other three (it's meant
    to read as "unremarkable good weather," not just "not extreme in
    exactly one specific way")."""
    buckets = set()
    if weather.rain_mm >= _RAINY_MM:
        buckets.add(RAINY)
    if weather.temp_mean_c <= _COLD_C:
        buckets.add(COLD)
    if weather.wind_speed_kph >= _WINDY_KPH:
        buckets.add(WINDY)
    if (
        weather.rain_mm < _RAINY_MM
        and _MILD_MIN_C <= weather.temp_mean_c <= _MILD_MAX_C
        and weather.wind_speed_kph < _WINDY_KPH
    ):
        buckets.add(MILD_DRY)
    return frozenset(buckets)


@dataclass(frozen=True)
class WeatherPatternComparison:
    category_id: uuid.UUID
    category_name: str
    bucket: str
    bucket_day_count: int
    other_day_count: int
    # Real average daily units on days matching `bucket`, vs. real average
    # daily units on every other day in the same history window — never a
    # Met Éireann value, always the business's own sales.
    avg_on_bucket_days: Decimal
    avg_on_other_days: Decimal
    # Signed: positive means more sold on bucket days than other days.
    pct_difference: Decimal


def compute_weather_pattern_comparison(
    daily_weather: dict[date, DailyWeather],
    daily_units_by_category: dict[uuid.UUID, dict[date, Decimal]],
    category_names: dict[uuid.UUID, str],
    *,
    min_bucket_days: int = MIN_BUCKET_DAYS,
    min_pct_difference: Decimal = DEFAULT_MIN_PCT_DIFFERENCE,
) -> list[WeatherPatternComparison]:
    """For every (category, bucket) pair, splits the shared history into
    days matching the bucket vs. every other day, and compares real
    average daily units sold between the two groups.

    Only days present in BOTH `daily_weather` and a category's own sales
    series are used — a category's sales history and the business's
    weather-observation history don't necessarily cover the exact same
    date range (weather starts accumulating from whenever this feature
    shipped; sales history can predate that by months), so this is never
    a synthetic zero-fill, only genuinely known days on both sides.

    Refuses to report a comparison below `min_bucket_days` real matching
    days (same "don't invent a pattern from too little data" posture as
    forecasting.py's MIN_HISTORY_DAYS), and refuses when the "other days"
    average is exactly zero (a percentage difference from a zero baseline
    is undefined, not a real number to report) or the real difference
    doesn't clear `min_pct_difference` (a materiality gate, not just a
    sample-size one — don't surface noise just because it's measurable).
    """
    results: list[WeatherPatternComparison] = []
    for category_id, daily_units in daily_units_by_category.items():
        shared_days = [d for d in daily_units if d in daily_weather]
        if not shared_days:
            continue

        buckets_by_day = {d: classify_day(daily_weather[d]) for d in shared_days}
        for bucket in BUCKETS:
            bucket_days = [d for d in shared_days if bucket in buckets_by_day[d]]
            other_days = [d for d in shared_days if bucket not in buckets_by_day[d]]
            if len(bucket_days) < min_bucket_days or not other_days:
                continue

            avg_on_bucket_days = sum((daily_units[d] for d in bucket_days), Decimal("0")) / len(bucket_days)
            avg_on_other_days = sum((daily_units[d] for d in other_days), Decimal("0")) / len(other_days)
            if avg_on_other_days == 0:
                continue

            pct_difference = (avg_on_bucket_days - avg_on_other_days) / avg_on_other_days * 100
            if abs(pct_difference) < min_pct_difference:
                continue

            results.append(
                WeatherPatternComparison(
                    category_id=category_id,
                    category_name=category_names.get(category_id, "Uncategorized"),
                    bucket=bucket,
                    bucket_day_count=len(bucket_days),
                    other_day_count=len(other_days),
                    avg_on_bucket_days=avg_on_bucket_days,
                    avg_on_other_days=avg_on_other_days,
                    pct_difference=pct_difference,
                )
            )
    return results


def classify_upcoming_buckets(
    forecast: list[DailyWeather], *, min_matching_days: int = DEFAULT_MIN_UPCOMING_MATCHING_DAYS
) -> frozenset[str]:
    """Which buckets the upcoming forecast genuinely looks like — needs at
    least `min_matching_days` of the forecast to match, not just one
    rainy day out of seven, before a caller frames anything around
    "conditions this week.\""""
    counts = {bucket: 0 for bucket in BUCKETS}
    for day in forecast:
        for bucket in classify_day(day):
            counts[bucket] += 1
    return frozenset(bucket for bucket, count in counts.items() if count >= min_matching_days)
