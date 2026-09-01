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
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.analytics.findings import Finding
from app.analytics.weather_patterns import (
    BUCKETS,
    DailyWeather,
    MIN_BUCKET_DAYS,
    WeatherPatternComparison,
    classify_day,
    classify_upcoming_buckets,
    compute_weather_pattern_comparison,
)
from app.application.forecast import (
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


@dataclass(frozen=True)
class WeatherSalesRanking:
    """One product or category ranked by units sold on matching weather days.

    units_sold is NET of returns (a return is a negative-quantity sale
    row, sign-bearing throughout this schema — see SaleItemRepository's
    own convention) — same "revenue/units already nets out returns"
    semantics every other unit-based figure in this app already has, so
    a product with more returns than sales in a bucket can legitimately
    show a negative value. Callers presenting this to a user should say
    "net units sold," not a bare "units sold," so a negative or
    near-zero figure reads as intentional rather than a mistake.

    This deliberately reports shop sales only. The weather bucket is ORLA's
    fixed classification; raw provider measurements never leave this layer.
    """

    name: str
    units_sold: Decimal
    average_units_per_matching_day: Decimal


@dataclass(frozen=True)
class WeatherSalesAnalysis:
    bucket: str
    bucket_day_count: int
    entity_type: str
    top: list[WeatherSalesRanking]
    bottom: list[WeatherSalesRanking]


def _load_weather_and_sales_data(
    db: Session, business: Business, now: datetime
) -> tuple[dict[date, DailyWeather], dict[uuid.UUID, dict[date, Decimal]], dict[uuid.UUID, str]] | None:
    """Shared data-loading for both `get_weather_pattern_findings` (below)
    and `get_weather_pattern_comparisons_for_category` — this business's
    own accumulated weather_observations history plus its per-category
    daily sales history, over the same real (never zero-filled) date
    range. Returns None whenever there's no resolved location or no
    weather history accumulated yet at all — both callers treat that the
    same way (an empty result, never an error).
    """
    if business.latitude is None or business.longitude is None:
        return None

    today = today_in_business_timezone(business.timezone, now)
    yesterday = today - timedelta(days=1)

    weather_rows = WeatherObservationRepository(db).list_in_range(
        business_id=business.id, start_date=date.min, end_date=yesterday
    )
    if not weather_rows:
        return None

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
        return None

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
        return None

    return daily_weather, {cid: dict(series) for cid, series in daily_units_by_category.items()}, category_names


def get_weather_pattern_comparisons_for_category(
    db: Session, *, business: Business, category_id: uuid.UUID, now: datetime | None = None
) -> list[WeatherPatternComparison]:
    """Real comparisons for ONE category, across every bucket with enough
    history — unlike `get_weather_pattern_findings` below, deliberately
    **not** gated on the upcoming forecast matching. This is "tell me
    what my own sales history shows for this category" (Ask ORLA's
    `weather_pattern_lookup` intent), not "tell me only what's relevant
    to this exact week" (the Finding, and `weather_outlook`). Empty list
    for the same reasons `get_weather_pattern_findings` returns []
    (no location, no history yet), plus when this specific category has
    no sales history in the loaded range at all.
    """
    resolved_now = now or datetime.now(ZoneInfo("UTC"))
    loaded = _load_weather_and_sales_data(db, business, resolved_now)
    if loaded is None:
        return []
    daily_weather, daily_units_by_category, category_names = loaded
    category_series = daily_units_by_category.get(category_id)
    if category_series is None:
        return []
    return compute_weather_pattern_comparison(daily_weather, {category_id: category_series}, category_names)


def get_weather_sales_rankings(
    db: Session,
    *,
    business: Business,
    bucket: str,
    entity_type: str,
    limit: int = 5,
    now: datetime | None = None,
) -> WeatherSalesAnalysis | None:
    """Ranks products or categories by real unit sales on one weather bucket.

    Unlike the weather-pattern comparison, this is a descriptive ranking,
    not a claim that weather caused a change in demand. Every day with an
    observed matching bucket counts in the average, including a zero-sales
    day. Rows with no matching-day sales are omitted so a "bottom" list is
    useful instead of being filled with arbitrary zero-selling catalogue
    items.
    """
    if bucket not in BUCKETS or entity_type not in {"product", "category"} or not 1 <= limit <= 10:
        return None

    resolved_now = now or datetime.now(ZoneInfo("UTC"))
    if business.latitude is None or business.longitude is None:
        return None

    today = today_in_business_timezone(business.timezone, resolved_now)
    weather_rows = WeatherObservationRepository(db).list_in_range(
        business_id=business.id, start_date=date.min, end_date=today - timedelta(days=1)
    )
    matching_days = {
        row.observed_date
        for row in weather_rows
        if bucket in classify_day(
            DailyWeather(
                day=row.observed_date,
                rain_mm=row.rain_mm,
                temp_mean_c=row.temp_mean_c,
                wind_speed_kph=row.wind_speed_kph,
            )
        )
    }
    if len(matching_days) < MIN_BUCKET_DAYS:
        return None

    query_start = local_midnight_utc(min(matching_days), business.timezone)
    query_end = local_midnight_utc(today, business.timezone)
    item_rows = SaleItemRepository(db).list_units_by_product_in_range(business.id, query_start, query_end)
    if not item_rows:
        return None

    products = {product.id: product for product in ProductRepository(db).list_for_business(business.id)}
    categories = {category.id: category.name for category in ProductCategoryRepository(db).list_for_business(business.id)}
    tz = ZoneInfo(business.timezone)
    units_by_entity: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    names: dict[uuid.UUID, str] = {}
    for product_id, sold_at, quantity in item_rows:
        if sold_at.astimezone(tz).date() not in matching_days:
            continue
        product = products.get(product_id)
        if product is None:
            continue
        if entity_type == "product":
            entity_id, name = product.id, product.name
        elif product.category_id is not None and product.category_id in categories:
            entity_id, name = product.category_id, categories[product.category_id]
        else:
            continue
        units_by_entity[entity_id] += Decimal(quantity)
        names[entity_id] = name

    if not units_by_entity:
        return None

    ranked = sorted(units_by_entity, key=lambda entity_id: (units_by_entity[entity_id], names[entity_id].lower()))

    def _row(entity_id: uuid.UUID) -> WeatherSalesRanking:
        units = units_by_entity[entity_id]
        average = (units / len(matching_days)).quantize(Decimal("0.1"))
        if average == 0:
            # Real bug, found live: a small negative units_sold (more
            # returns than sales on matching days — quantity is sign-
            # bearing everywhere in this schema, see SaleItemRepository's
            # own convention) can round to Decimal("-0.0") once divided
            # by a large day count, e.g. -1/82 quantized to one decimal.
            # -0.0 == 0.0 is True in Python, so this normalizes to the
            # positive-zero Decimal without changing which value it is —
            # only how it *displays* ("0.0" per matching day, not the
            # misleading "-0.0").
            average = abs(average)
        return WeatherSalesRanking(
            name=names[entity_id],
            units_sold=units,
            average_units_per_matching_day=average,
        )

    return WeatherSalesAnalysis(
        bucket=bucket,
        bucket_day_count=len(matching_days),
        entity_type=entity_type,
        top=[_row(entity_id) for entity_id in reversed(ranked[-limit:])],
        bottom=[_row(entity_id) for entity_id in ranked[:limit]],
    )


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
    resolved_now = now or datetime.now(ZoneInfo("UTC"))
    loaded = _load_weather_and_sales_data(db, business, resolved_now)
    if loaded is None:
        return []
    daily_weather, daily_units_by_category, category_names = loaded
    today = today_in_business_timezone(business.timezone, resolved_now)

    comparisons = compute_weather_pattern_comparison(daily_weather, daily_units_by_category, category_names)
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
