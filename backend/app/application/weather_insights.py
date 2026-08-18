"""Orchestrates the weather-pattern Finding for one business: pulls its
own stored weather_observations history (app/repositories/
weather_observation.py — ORLA's own accumulated daily record, never Met
Éireann's historical archive, which is unavailable — see
app/application/weather_ingestion.py), its per-category daily sales
history, and the upcoming forecast, then calls the pure comparison
functions in app/analytics/weather_patterns.py. No calculation logic of
its own — see CLAUDE.md's "Business Logic First".

Compliance boundary, direct instruction: nothing built here may ever
surface a Met Éireann figure itself. Every Finding's `evidence` below
carries only the bucket label (ORLA's own classification) and the
business's own real sales numbers — never a raw rain-mm/temp-C/wind-kph
value. See docs/governance/11_Development_Roadmap.md v1.80.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.analytics.findings import Finding
from app.analytics.weather_patterns import (
    DailyWeather,
    classify_upcoming_buckets,
    compute_weather_pattern_comparison,
)
from app.application.forecast import (
    _earliest_local_date as earliest_local_date,
    _local_midnight_utc as local_midnight_utc,
    _today_in_business_timezone as today_in_business_timezone,
)
from app.models.business import Business
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.sale_item import SaleItemRepository
from app.repositories.weather_observation import WeatherObservationRepository
from app.weather import client as weather_client
from app.weather.exceptions import WeatherProviderError

# Plain-language phrasing for each fixed bucket (app/analytics/
# weather_patterns.py::BUCKETS) — ORLA's own classification, not a Met
# Éireann value, so safe to name directly in a Finding's message per the
# compliance boundary above.
_BUCKET_PHRASES = {
    "rainy": "rainy conditions",
    "cold": "cold conditions",
    "windy": "windy conditions",
    "mild_dry": "mild, dry conditions",
}


def get_weather_pattern_findings(db: Session, *, business: Business, now: datetime | None = None) -> list[Finding]:
    """Zero or more Findings — never raises. Returns [] whenever: the
    business has no resolved latitude/longitude yet (see
    app/geocoding/service.py::resolve_and_persist_coordinates), no
    weather_observations history has accumulated yet at all, the live
    forecast call fails, or nothing clears app/analytics/
    weather_patterns.py's own sample-size/materiality gates. Same
    graceful-degradation posture as every other optional signal in this
    codebase.
    """
    if business.latitude is None or business.longitude is None:
        return []

    resolved_now = now or datetime.now(ZoneInfo("UTC"))
    today = today_in_business_timezone(business.timezone, resolved_now)
    yesterday = today - timedelta(days=1)

    weather_rows = WeatherObservationRepository(db).list_in_range(
        business_id=business.id, start_date=date.min, end_date=yesterday
    )
    if not weather_rows:
        return []

    daily_weather: dict[date, DailyWeather] = {
        row.observed_date: DailyWeather(
            day=row.observed_date, rain_mm=row.rain_mm, temp_mean_c=row.temp_mean_c, wind_speed_kph=row.wind_speed_kph
        )
        for row in weather_rows
    }

    earliest_weather_date = min(daily_weather)
    query_start = local_midnight_utc(earliest_weather_date, business.timezone)
    query_end = local_midnight_utc(today, business.timezone)  # exclusive — never a partial "today"

    item_rows = SaleItemRepository(db).list_units_by_product_in_range(business.id, query_start, query_end)
    if not item_rows:
        return []

    products = ProductRepository(db).list_for_business(business.id)
    category_by_product = {p.id: p.category_id for p in products if p.category_id is not None}
    category_names = {c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business.id)}

    tz = ZoneInfo(business.timezone)
    daily_units_by_category: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for product_id, sold_at, quantity in item_rows:
        category_id = category_by_product.get(product_id)
        if category_id is None:
            continue
        local_date = sold_at.astimezone(tz).date()
        daily_units_by_category[category_id][local_date] += Decimal(quantity)

    if not daily_units_by_category:
        return []

    comparisons = compute_weather_pattern_comparison(
        daily_weather, {cid: dict(series) for cid, series in daily_units_by_category.items()}, category_names
    )
    if not comparisons:
        return []

    try:
        forecast_days = weather_client.get_forecast(
            lat=business.latitude, lon=business.longitude, business_timezone=business.timezone
        )
    except WeatherProviderError:
        return []

    upcoming_weather = [
        DailyWeather(day=d.day, rain_mm=d.rain_mm, temp_mean_c=d.temp_mean_c, wind_speed_kph=d.wind_speed_kph)
        for d in forecast_days
        if d.day >= today
    ]
    upcoming_buckets = classify_upcoming_buckets(upcoming_weather)
    if not upcoming_buckets:
        return []

    findings: list[Finding] = []
    for comparison in comparisons:
        if comparison.bucket not in upcoming_buckets:
            continue
        direction = "more" if comparison.pct_difference > 0 else "less"
        findings.append(
            Finding(
                type="weather_pattern_insight",
                severity="info",
                message=(
                    f"Conditions like the ones forecast this week ({_BUCKET_PHRASES[comparison.bucket]}) have "
                    f"historically meant {abs(comparison.pct_difference):.0f}% {direction} demand for "
                    f"{comparison.category_name}, based on {comparison.bucket_day_count} similar days in your "
                    f"own sales history."
                ),
                evidence={
                    "category_id": str(comparison.category_id),
                    "category_name": comparison.category_name,
                    "bucket": comparison.bucket,
                    "bucket_day_count": comparison.bucket_day_count,
                    "other_day_count": comparison.other_day_count,
                    "avg_on_bucket_days": comparison.avg_on_bucket_days,
                    "avg_on_other_days": comparison.avg_on_other_days,
                    "pct_difference": comparison.pct_difference,
                },
                rule_id="weather_pattern_insight",
            )
        )
    return findings
