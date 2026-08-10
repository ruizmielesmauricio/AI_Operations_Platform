"""Combines every dashboard section across a standalone shop and its
branches into one "All branches" view — direct request, scoped up front
via a clarifying question: covers all five sections (Financial, Retail,
Workshop, Forecast, Findings), and only offered when every business in the
group shares one timezone (never silently blends two different "this
week"s into one number).

Design, matching CLAUDE.md's Business Logic First: every function below
sums or concatenates *raw* per-business inputs (repository query results,
before any ratio/percentage is computed) across the group, then calls the
exact same, already-tested pure formula from app/analytics/*.py exactly
once over the combined data — never merges already-computed per-business
percentages (which would silently average unrelated rates instead of
computing one true combined rate) and never duplicates a formula's logic.
A product/category id is a UUID scoped to exactly one business's own
table, so merging per-product/per-category dicts across businesses is a
plain, collision-free union, not a real "combination" — the only place
raw numbers actually need summing is whole-business totals (revenue,
returns, repair totals) and concatenated per-product/day row lists.
"""

import math
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analytics.financial import (
    compute_gross_margin,
    compute_returns_summary,
    compute_revenue_change,
    rank_products_by_margin,
)
from app.analytics.findings import build_recommendations, evaluate_all
from app.analytics.forecasting import MAX_LOOKBACK_DAYS, compute_baseline_forecast
from app.analytics.period import group_amounts_by_local_date, resolve_period
from app.analytics.retail import (
    build_stock_cover_report,
    compute_inventory_value_at_cost,
    compute_sell_through_rate,
    find_dead_stock,
    rank_top_sellers_by_revenue,
    rank_top_sellers_by_units,
)
from app.analytics.types import ProductPeriodAggregate, RepairPeriodTotals
from app.analytics.workshop import compute_workshop_margin
from app.application.financial_performance import FinancialPerformanceSummary
from app.application.findings import FindingsSummary
from app.application.forecast import ForecastSummary, ProductDemandForecast, RevenueForecastSummary

# Reused directly rather than duplicated: these are pure, already-tested
# helpers private to app/application/forecast.py (date-boundary math and
# money/unit Decimal quantization) — re-implementing the same rounding
# rules a second time here is a strictly worse risk than importing them
# by their real (underscore-prefixed) names. Not a public API, just this
# codebase's own internal reuse.
from app.application.forecast import (
    _earliest_local_date as earliest_local_date,
    _local_midnight_utc as local_midnight_utc,
    _NO_COVER_SORT_KEY as NO_COVER_SORT_KEY,
    _quantize_forecast_result as quantize_forecast_result,
    _quantize_money as quantize_forecast_money,
    _quantize_units as quantize_forecast_units,
    _today_in_business_timezone as today_in_business_timezone,
)
from app.application.retail_operations import RetailOperationsSummary
from app.application.workshop_performance import WorkshopPerformanceSummary
from app.models.business import Business
from app.models.membership import Membership
from app.repositories.business import get_business_group
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.production_event import ProductionEventRepository
from app.repositories.return_ import ReturnRepository
from app.repositories.sale import SaleRepository
from app.repositories.sale_item import SaleItemRepository

_TOP_N = 5


class BusinessNotFound(Exception):
    """No live (non-deleted) business matches the given id."""


class NotGroupMember(Exception):
    """The caller isn't a member of every business in the resolved group.

    Checked per business explicitly, never assumed from the group
    relationship alone — a manager could be added to just one branch and
    not the primary shop (or vice versa), and combining data across
    businesses is a new capability this codebase never had before, so it
    gets its own explicit authorization pass rather than piggy-backing on
    "you're a member of the business_id in the URL."
    """


class MixedTimezoneGroup(Exception):
    """The businesses in this group don't all share one timezone.

    Direct scope decision: require a match rather than picking one
    business's timezone as authoritative for the rest — combining under
    mismatched timezones would silently blend two different "this
    week"s into one number with no way for the reader to tell.
    """

    def __init__(self, timezones: list[str]):
        self.timezones = timezones
        super().__init__(f"Businesses in this group don't share one timezone: {timezones}")


def resolve_authorized_group(db: Session, *, business_id: uuid.UUID, user_id: str) -> list[Business]:
    group = get_business_group(db, business_id=business_id)
    if group is None:
        raise BusinessNotFound(str(business_id))
    for business in group:
        membership = (
            db.query(Membership)
            .filter(Membership.business_id == business.id, Membership.user_id == user_id)
            .first()
        )
        if membership is None:
            raise NotGroupMember(str(business.id))
    timezones = sorted({business.timezone for business in group})
    if len(timezones) > 1:
        raise MixedTimezoneGroup(timezones)
    return group


def _merge_category_names(db: Session, business: Business, products: list) -> dict[uuid.UUID, str | None]:
    category_name_by_id = {c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business.id)}
    return {
        product.id: (category_name_by_id.get(product.category_id) if product.category_id else None)
        for product in products
    }


def get_financial_performance_for_group(
    db: Session,
    *,
    businesses: list[Business],
    start_date: date | None = None,
    end_date: date | None = None,
    category_id: uuid.UUID | None = None,
) -> FinancialPerformanceSummary:
    # All group members share one timezone (resolve_authorized_group's own
    # precondition), so any one of them resolves the same period as the
    # rest.
    period = resolve_period(businesses[0].timezone, start_date, end_date)
    previous_period = period.previous()

    products_by_id: dict[uuid.UUID, str] = {}
    category_name_by_product: dict[uuid.UUID, str | None] = {}
    aggregates: list[ProductPeriodAggregate] = []
    current_revenue = Decimal("0")
    previous_revenue = Decimal("0")
    returns_amount = Decimal("0")
    return_count = 0

    for business in businesses:
        products = ProductRepository(db).list_for_business(business.id)
        if category_id is not None:
            products = [p for p in products if p.category_id == category_id]
        business_products_by_id = {p.id: p.name for p in products}
        products_by_id.update(business_products_by_id)
        category_name_by_product.update(_merge_category_names(db, business, products))

        business_aggregates = SaleItemRepository(db).aggregate_by_product_in_range(
            business.id, period.start, period.end
        )
        business_previous_aggregates = SaleItemRepository(db).aggregate_by_product_in_range(
            business.id, previous_period.start, previous_period.end
        )

        if category_id is not None:
            business_aggregates = [a for a in business_aggregates if a.product_id in business_products_by_id]
            business_previous_aggregates = [
                a for a in business_previous_aggregates if a.product_id in business_products_by_id
            ]
            current_revenue += sum((a.revenue for a in business_aggregates), Decimal("0"))
            previous_revenue += sum((a.revenue for a in business_previous_aggregates), Decimal("0"))
        else:
            current_revenue += SaleRepository(db).sum_total_amount_in_range(business.id, period.start, period.end)
            previous_revenue += SaleRepository(db).sum_total_amount_in_range(
                business.id, previous_period.start, previous_period.end
            )

        aggregates.extend(business_aggregates)
        returns_amount += ReturnRepository(db).sum_refund_amount_in_range(business.id, period.start, period.end)
        return_count += ReturnRepository(db).count_in_range(business.id, period.start, period.end)

    revenue_trend = compute_revenue_change(current_revenue, previous_revenue)
    gross_margin = compute_gross_margin(aggregates)
    top, bottom, excluded_count, all_margin_products = rank_products_by_margin(
        aggregates, products_by_id, top_n=_TOP_N, category_name_by_product=category_name_by_product
    )
    returns_summary = compute_returns_summary(current_revenue, returns_amount, return_count)

    return FinancialPerformanceSummary(
        period=period,
        previous_period=previous_period,
        revenue=revenue_trend,
        gross_margin=gross_margin,
        top_margin_products=top,
        bottom_margin_products=bottom,
        products_excluded_from_ranking=excluded_count,
        returns=returns_summary,
        all_margin_products=all_margin_products,
    )


def get_retail_operations_for_group(
    db: Session,
    *,
    businesses: list[Business],
    start_date: date | None = None,
    end_date: date | None = None,
    category_id: uuid.UUID | None = None,
) -> RetailOperationsSummary:
    period = resolve_period(businesses[0].timezone, start_date, end_date)

    products_by_id: dict[uuid.UUID, str] = {}
    cost_price_by_product: dict[uuid.UUID, Decimal | None] = {}
    category_name_by_product: dict[uuid.UUID, str | None] = {}
    stock_by_product: dict[uuid.UUID, int] = {}
    aggregates: list[ProductPeriodAggregate] = []

    for business in businesses:
        products = ProductRepository(db).list_for_business(business.id)
        if category_id is not None:
            products = [p for p in products if p.category_id == category_id]
        business_products_by_id = {p.id: p.name for p in products}
        products_by_id.update(business_products_by_id)
        cost_price_by_product.update({p.id: p.cost_price for p in products})
        category_name_by_product.update(_merge_category_names(db, business, products))

        product_ids = list(business_products_by_id.keys())
        business_stock = InventoryMovementRepository(db).sum_by_product_ids(business.id, product_ids)
        for product_id in product_ids:
            business_stock.setdefault(product_id, 0)
        stock_by_product.update(business_stock)

        business_aggregates = SaleItemRepository(db).aggregate_by_product_in_range(
            business.id, period.start, period.end
        )
        if category_id is not None:
            business_aggregates = [a for a in business_aggregates if a.product_id in business_products_by_id]
        aggregates.extend(business_aggregates)

    aggregates_by_product = {a.product_id: a for a in aggregates}

    top_sellers_by_units = rank_top_sellers_by_units(
        aggregates, products_by_id, top_n=_TOP_N, category_name_by_product=category_name_by_product
    )
    top_sellers_by_revenue = rank_top_sellers_by_revenue(
        aggregates, products_by_id, top_n=_TOP_N, category_name_by_product=category_name_by_product
    )
    stock_cover = build_stock_cover_report(
        aggregates_by_product,
        stock_by_product,
        products_by_id,
        period.days,
        category_name_by_product=category_name_by_product,
    )
    dead_stock = find_dead_stock(
        aggregates_by_product,
        stock_by_product,
        products_by_id,
        cost_price_by_product,
        category_name_by_product=category_name_by_product,
    )
    inventory_value = compute_inventory_value_at_cost(stock_by_product, cost_price_by_product)

    total_units_sold = sum(a.units_sold for a in aggregates)
    total_stock_on_hand = sum(stock_by_product.values())
    sell_through_rate = compute_sell_through_rate(total_units_sold, total_stock_on_hand)

    return RetailOperationsSummary(
        period=period,
        top_sellers_by_units=top_sellers_by_units,
        top_sellers_by_revenue=top_sellers_by_revenue,
        stock_cover=stock_cover,
        dead_stock=dead_stock,
        inventory_value=inventory_value,
        sell_through_rate=sell_through_rate,
    )


def _sum_repair_totals(a: RepairPeriodTotals, b: RepairPeriodTotals) -> RepairPeriodTotals:
    return RepairPeriodTotals(
        repair_count=a.repair_count + b.repair_count,
        repairs_with_known_price=a.repairs_with_known_price + b.repairs_with_known_price,
        revenue=a.revenue + b.revenue,
        repairs_with_known_price_and_labour=a.repairs_with_known_price_and_labour
        + b.repairs_with_known_price_and_labour,
        labour_cost_known_revenue=a.labour_cost_known_revenue + b.labour_cost_known_revenue,
        labour_cost=a.labour_cost + b.labour_cost,
    )


_EMPTY_REPAIR_TOTALS = RepairPeriodTotals(
    repair_count=0,
    repairs_with_known_price=0,
    revenue=Decimal("0"),
    repairs_with_known_price_and_labour=0,
    labour_cost_known_revenue=Decimal("0"),
    labour_cost=Decimal("0"),
)


def get_workshop_performance_for_group(
    db: Session,
    *,
    businesses: list[Business],
    start_date: date | None = None,
    end_date: date | None = None,
) -> WorkshopPerformanceSummary:
    period = resolve_period(businesses[0].timezone, start_date, end_date)
    previous_period = period.previous()
    repo = ProductionEventRepository(db)

    totals = _EMPTY_REPAIR_TOTALS
    previous_totals = _EMPTY_REPAIR_TOTALS
    for business in businesses:
        totals = _sum_repair_totals(totals, repo.aggregate_completed_repairs_in_range(business.id, period.start, period.end))
        previous_totals = _sum_repair_totals(
            previous_totals,
            repo.aggregate_completed_repairs_in_range(business.id, previous_period.start, previous_period.end),
        )

    margin = compute_workshop_margin(totals)
    revenue_trend = compute_revenue_change(totals.revenue, previous_totals.revenue)
    return WorkshopPerformanceSummary(period=period, revenue=revenue_trend, margin=margin)


def get_findings_for_group(
    db: Session,
    *,
    businesses: list[Business],
    start_date: date | None = None,
    end_date: date | None = None,
    category_id: uuid.UUID | None = None,
) -> FindingsSummary:
    # Exactly mirrors app/application/findings.py::get_findings, just
    # against the group-aggregate financial/retail summaries above instead
    # of one business's own — the rule functions themselves (evaluate_all,
    # build_recommendations) are completely unaware anything is combined.
    financial = get_financial_performance_for_group(
        db, businesses=businesses, start_date=start_date, end_date=end_date
    )
    retail = get_retail_operations_for_group(db, businesses=businesses, start_date=start_date, end_date=end_date)

    product_financial = financial
    product_retail = retail
    if category_id is not None:
        product_financial = get_financial_performance_for_group(
            db, businesses=businesses, start_date=start_date, end_date=end_date, category_id=category_id
        )
        product_retail = get_retail_operations_for_group(
            db, businesses=businesses, start_date=start_date, end_date=end_date, category_id=category_id
        )

    findings = evaluate_all(
        revenue=financial.revenue,
        gross_margin=financial.gross_margin,
        top_margin_products=product_financial.top_margin_products,
        bottom_margin_products=product_financial.bottom_margin_products,
        all_margin_products=product_financial.all_margin_products,
        stock_cover=product_retail.stock_cover,
        dead_stock=product_retail.dead_stock,
        returns=financial.returns,
    )
    recommendations = build_recommendations(findings)
    return FindingsSummary(period=financial.period, findings=findings, recommendations=recommendations)


def get_forecast_for_group(
    db: Session,
    *,
    businesses: list[Business],
    horizon_days: int = 7,
    now: datetime | None = None,
    category_id: uuid.UUID | None = None,
) -> ForecastSummary:
    business_timezone = businesses[0].timezone
    today = today_in_business_timezone(business_timezone, now)
    max_lookback_start = today - timedelta(days=MAX_LOOKBACK_DAYS)
    window_end = today - timedelta(days=1)
    query_start = local_midnight_utc(max_lookback_start, business_timezone)
    query_end = local_midnight_utc(today, business_timezone)

    # --- Revenue ---------------------------------------------------------
    # Raw (timestamp, amount) rows concatenated across the whole group
    # *before* bucketing into local-calendar-day totals — bucket-then-sum
    # commutes with concatenation, so this is exactly the daily series the
    # group would produce if it were one shared sales table, then runs the
    # *same*, unmodified compute_baseline_forecast over it. No separate
    # confidence-band-combination formula invented — the existing model
    # just sees more history, the same way it would for one bigger
    # business.
    sale_rows: list[tuple[datetime, Decimal]] = []
    for business in businesses:
        sale_rows.extend(SaleRepository(db).list_amounts_in_range(business.id, query_start, query_end))
    revenue_first_seen = earliest_local_date(sale_rows, business_timezone)
    if revenue_first_seen is None:
        revenue_result = compute_baseline_forecast({}, horizon_days, today=today)
    else:
        revenue_daily = group_amounts_by_local_date(
            sale_rows, business_timezone, window_start=revenue_first_seen, window_end=window_end
        )
        revenue_result = compute_baseline_forecast(revenue_daily, horizon_days, today=today)
    revenue_result = quantize_forecast_result(revenue_result, quantize_forecast_money)
    revenue = RevenueForecastSummary(horizon_days=horizon_days, result=revenue_result)

    # --- Per product -------------------------------------------------------
    # A product belongs to exactly one business's own catalogue (Product is
    # tenant-scoped), so per-product forecasting is never really "combined"
    # math — every dict merge below is a plain, collision-free union across
    # the group, one business's own repository calls at a time (each
    # InventoryMovementRepository/SaleItemRepository call still has to stay
    # scoped to its own business_id).
    rows_by_product: dict[uuid.UUID, list[tuple[datetime, Decimal]]] = {}
    products_by_id: dict[uuid.UUID, object] = {}
    stock_by_product: dict[uuid.UUID, int] = {}
    category_name_by_id: dict[uuid.UUID, str] = {}

    for business in businesses:
        item_rows = SaleItemRepository(db).list_units_by_product_in_range(business.id, query_start, query_end)
        business_rows_by_product: dict[uuid.UUID, list[tuple[datetime, Decimal]]] = {}
        for product_id, sold_at, quantity in item_rows:
            business_rows_by_product.setdefault(product_id, []).append((sold_at, Decimal(quantity)))
        rows_by_product.update(business_rows_by_product)

        business_products = ProductRepository(db).list_for_business(business.id)
        if category_id is not None:
            business_products = [p for p in business_products if p.category_id == category_id]
        business_products_by_id = {p.id: p for p in business_products}
        products_by_id.update(business_products_by_id)

        business_stock = InventoryMovementRepository(db).sum_by_product_ids(
            business.id, list(business_rows_by_product.keys())
        )
        stock_by_product.update(business_stock)

        category_name_by_id.update({c.id: c.name for c in ProductCategoryRepository(db).list_for_business(business.id)})

    products: list[ProductDemandForecast] = []
    excluded = 0
    for product_id, product in products_by_id.items():
        rows = rows_by_product.get(product_id, [])
        if not rows:
            excluded += 1
            continue

        first_seen = earliest_local_date(rows, business_timezone)
        daily = group_amounts_by_local_date(rows, business_timezone, window_start=first_seen, window_end=window_end)
        result = compute_baseline_forecast(daily, horizon_days, today=today)
        if result.insufficient_data:
            excluded += 1
            continue
        result = quantize_forecast_result(result, quantize_forecast_units)

        current_stock = stock_by_product.get(product_id, 0)
        suggested_reorder_quantity = max(0, math.ceil(result.total_high) - current_stock)
        daily_rate = result.total_point / horizon_days
        if current_stock <= 0:
            days_of_cover = Decimal("0")
        elif daily_rate > 0:
            days_of_cover = quantize_forecast_units(Decimal(current_stock) / daily_rate)
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
                category_name=category_name_by_id.get(product.category_id) if product.category_id else None,
            )
        )

    products.sort(
        key=lambda p: p.days_of_cover_at_forecast_rate if p.days_of_cover_at_forecast_rate is not None else NO_COVER_SORT_KEY
    )

    return ForecastSummary(
        horizon_days=horizon_days,
        revenue=revenue,
        products=products,
        products_excluded_insufficient_data=excluded,
    )
