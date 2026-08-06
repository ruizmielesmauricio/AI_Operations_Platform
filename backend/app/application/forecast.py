"""Orchestrates Stage C13's forecast summary for a route: resolves "today"
in the business's timezone, pulls raw per-day series from the
repositories, and feeds them into the pure baseline in
app/analytics/forecasting.py. No calculation logic of its own — see
CLAUDE.md's "Business Logic First".
"""

import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.analytics.forecasting import (
    MAX_LOOKBACK_DAYS,
    DailyForecast,
    ForecastResult,
    compute_baseline_forecast,
)
from app.analytics.period import group_amounts_by_local_date
from app.models.business import Business
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductRepository
from app.repositories.sale import SaleRepository
from app.repositories.sale_item import SaleItemRepository

_CENTS = Decimal("0.01")
_TENTH_UNIT = Decimal("0.1")
_NO_COVER_SORT_KEY = Decimal("Infinity")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _quantize_units(value: Decimal) -> Decimal:
    return value.quantize(_TENTH_UNIT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RevenueForecastSummary:
    horizon_days: int
    result: ForecastResult  # values in money terms, quantized to cents


@dataclass(frozen=True)
class ProductDemandForecast:
    product_id: uuid.UUID
    name: str
    sku: str | None
    result: ForecastResult  # values in unit terms, quantized to 0.1
    current_stock: int
    # max(0, ceil(result.total_high) - current_stock) — a cautious starting
    # suggestion using the confidence band's high end, not just the point
    # estimate. Does NOT model supplier lead time or safety stock — a
    # simple starting point, not a full reorder-planning system.
    suggested_reorder_quantity: int
    # Days of stock left at the forecasted daily rate — None when the
    # forecast's daily rate is 0 (nothing to divide by; not "infinite").
    # Lower is more urgent; products sort ascending by this (None last).
    days_of_cover_at_forecast_rate: Decimal | None


@dataclass(frozen=True)
class ForecastSummary:
    horizon_days: int
    revenue: RevenueForecastSummary
    products: list[ProductDemandForecast]
    products_excluded_insufficient_data: int


def _today_in_business_timezone(business_timezone: str, now: datetime | None = None) -> date:
    tz = ZoneInfo(business_timezone)
    current_time = (now or datetime.now(timezone.utc)).astimezone(tz)
    return current_time.date()


def _local_midnight_utc(local_date: date, business_timezone: str) -> datetime:
    tz = ZoneInfo(business_timezone)
    return datetime.combine(local_date, time.min, tzinfo=tz).astimezone(timezone.utc)


def _quantize_forecast_result(result: ForecastResult, quantize) -> ForecastResult:
    if result.insufficient_data:
        return result
    daily = [
        DailyForecast(forecast_date=d.forecast_date, point=quantize(d.point), low=quantize(d.low), high=quantize(d.high))
        for d in result.daily
    ]
    return ForecastResult(
        insufficient_data=False,
        method=result.method,
        history_days_used=result.history_days_used,
        daily=daily,
        total_point=quantize(result.total_point),
        total_low=quantize(result.total_low),
        total_high=quantize(result.total_high),
    )


def _earliest_local_date(rows: list[tuple], business_timezone: str) -> date | None:
    """The earliest business-local calendar date among (timestamp, ...)
    rows, or None if there are no rows at all. Used as the real start of
    the averaging window — a synthetic zero-fill all the way back to
    MAX_LOOKBACK_DAYS regardless of when the business's data actually
    begins would make a brand-new business's forecast gate
    (MIN_HISTORY_DAYS in forecasting.py) never trigger, since a
    fully-zero-filled window always has the same length no matter how
    little real history exists."""
    tz = ZoneInfo(business_timezone)
    dates = (row[0].astimezone(tz).date() for row in rows)
    return min(dates, default=None)


def get_forecast(
    db: Session,
    *,
    business_id: uuid.UUID,
    horizon_days: int = 7,
    now: datetime | None = None,
) -> ForecastSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    today = _today_in_business_timezone(business.timezone, now)
    max_lookback_start = today - timedelta(days=MAX_LOOKBACK_DAYS)
    window_end = today - timedelta(days=1)  # never includes partial "today"

    query_start = _local_midnight_utc(max_lookback_start, business.timezone)
    query_end = _local_midnight_utc(today, business.timezone)  # exclusive

    # --- Revenue -------------------------------------------------------
    sale_rows = SaleRepository(db).list_amounts_in_range(business_id, query_start, query_end)
    revenue_first_seen = _earliest_local_date(sale_rows, business.timezone)
    if revenue_first_seen is None:
        revenue_result = compute_baseline_forecast({}, horizon_days, today=today)
    else:
        revenue_daily = group_amounts_by_local_date(
            sale_rows, business.timezone, window_start=revenue_first_seen, window_end=window_end
        )
        revenue_result = compute_baseline_forecast(revenue_daily, horizon_days, today=today)
    revenue_result = _quantize_forecast_result(revenue_result, _quantize_money)
    revenue = RevenueForecastSummary(horizon_days=horizon_days, result=revenue_result)

    # --- Per product -----------------------------------------------------
    item_rows = SaleItemRepository(db).list_units_by_product_in_range(business_id, query_start, query_end)
    rows_by_product: dict[uuid.UUID, list[tuple[datetime, Decimal]]] = {}
    for product_id, sold_at, quantity in item_rows:
        rows_by_product.setdefault(product_id, []).append((sold_at, Decimal(quantity)))

    products_by_id = {p.id: p for p in ProductRepository(db).list_for_business(business_id)}
    stock_by_product = InventoryMovementRepository(db).sum_by_product_ids(business_id, list(rows_by_product.keys()))

    products: list[ProductDemandForecast] = []
    excluded = 0
    # Iterate every catalog product, not just ones with sales rows — a
    # product with zero sales anywhere in the window is just as much "not
    # enough data to forecast" as one with a few sales spanning under
    # MIN_HISTORY_DAYS, and both should count toward the same disclosure
    # total (same precedent as products_excluded_from_ranking in
    # FinancialPerformanceSummary — the count should be honest about the
    # whole catalog, not just the subset that had any activity at all).
    for product_id, product in products_by_id.items():
        rows = rows_by_product.get(product_id, [])
        if not rows:
            excluded += 1
            continue

        first_seen = _earliest_local_date(rows, business.timezone)
        daily = group_amounts_by_local_date(rows, business.timezone, window_start=first_seen, window_end=window_end)
        result = compute_baseline_forecast(daily, horizon_days, today=today)
        if result.insufficient_data:
            excluded += 1
            continue
        result = _quantize_forecast_result(result, _quantize_units)

        current_stock = stock_by_product.get(product_id, 0)
        suggested_reorder_quantity = max(0, math.ceil(result.total_high) - current_stock)
        daily_rate = result.total_point / horizon_days
        # 0, not a negative number, when there's no stock at all — same
        # convention as compute_stock_cover_days in app/analytics/retail.py
        # (stock_on_hand <= 0 -> 0 days left, never a negative "days of
        # cover"). current_stock can go negative when derived stock has
        # been driven below zero (e.g. sales recorded with no matching
        # purchase/inventory-count import yet) — that's a real
        # data-completeness issue for RetailSection to flag, not something
        # this division should turn into a nonsensical negative day count.
        if current_stock <= 0:
            days_of_cover = Decimal("0")
        elif daily_rate > 0:
            days_of_cover = _quantize_units(Decimal(current_stock) / daily_rate)
        else:
            days_of_cover = None

        products.append(
            ProductDemandForecast(
                product_id=product_id,
                name=product.name,
                sku=product.sku,
                result=result,
                current_stock=current_stock,
                suggested_reorder_quantity=suggested_reorder_quantity,
                days_of_cover_at_forecast_rate=days_of_cover,
            )
        )

    # Most urgent (least cover) first; products with no forecast-implied
    # depletion (days_of_cover is None) sort last — there's nothing urgent
    # about a product forecast to sell zero.
    products.sort(key=lambda p: p.days_of_cover_at_forecast_rate if p.days_of_cover_at_forecast_rate is not None else _NO_COVER_SORT_KEY)

    return ForecastSummary(
        horizon_days=horizon_days,
        revenue=revenue,
        products=products,
        products_excluded_insufficient_data=excluded,
    )
