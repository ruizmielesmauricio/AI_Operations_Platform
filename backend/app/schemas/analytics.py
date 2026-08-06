import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class PeriodOut(BaseModel):
    start: datetime
    end: datetime

    model_config = {"from_attributes": True}


class RevenueOut(BaseModel):
    current: Decimal
    previous: Decimal
    change_pct: Decimal | None

    model_config = {"from_attributes": True}


class GrossMarginOut(BaseModel):
    total_revenue: Decimal
    revenue_with_known_cost: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal | None
    cost_data_coverage_pct: Decimal | None
    net_gross_profit: Decimal | None
    net_gross_margin_pct: Decimal | None
    tax_data_coverage_pct: Decimal | None

    model_config = {"from_attributes": True}


class ProductMarginOut(BaseModel):
    product_id: uuid.UUID
    name: str
    revenue: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal

    model_config = {"from_attributes": True}


class FinancialPerformanceOut(BaseModel):
    period: PeriodOut
    revenue: RevenueOut
    gross_margin: GrossMarginOut
    top_margin_products: list[ProductMarginOut]
    bottom_margin_products: list[ProductMarginOut]
    products_excluded_from_ranking: int

    model_config = {"from_attributes": True}


class ProductSalesOut(BaseModel):
    product_id: uuid.UUID
    name: str
    units_sold: int
    revenue: Decimal

    model_config = {"from_attributes": True}


class StockCoverOut(BaseModel):
    product_id: uuid.UUID
    name: str
    stock_on_hand: int
    units_sold_in_period: int
    cover_days: Decimal | None
    revenue_in_period: Decimal

    model_config = {"from_attributes": True}


class DeadStockOut(BaseModel):
    product_id: uuid.UUID
    name: str
    stock_on_hand: int
    value_at_cost: Decimal | None

    model_config = {"from_attributes": True}


class InventoryValueOut(BaseModel):
    value_at_cost: Decimal
    products_missing_cost: int

    model_config = {"from_attributes": True}


class RetailOperationsOut(BaseModel):
    period: PeriodOut
    top_sellers_by_units: list[ProductSalesOut]
    top_sellers_by_revenue: list[ProductSalesOut]
    stock_cover: list[StockCoverOut]
    dead_stock: list[DeadStockOut]
    inventory_value: InventoryValueOut
    sell_through_rate: Decimal | None

    model_config = {"from_attributes": True}


class WorkshopMarginOut(BaseModel):
    repair_count: int
    revenue: Decimal
    revenue_coverage_pct: Decimal | None
    labour_cost: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal | None
    labour_cost_coverage_pct: Decimal | None
    average_ticket: Decimal | None

    model_config = {"from_attributes": True}


class WorkshopPerformanceOut(BaseModel):
    period: PeriodOut
    revenue: RevenueOut
    margin: WorkshopMarginOut

    model_config = {"from_attributes": True}


class FindingOut(BaseModel):
    type: str
    severity: str
    message: str
    evidence: dict
    rule_id: str
    rule_version: int

    model_config = {"from_attributes": True}


class RecommendationOut(BaseModel):
    finding_type: str
    severity: str
    title: str
    description: str
    evidence: dict
    impact_score: Decimal

    model_config = {"from_attributes": True}


class FindingsOut(BaseModel):
    period: PeriodOut
    findings: list[FindingOut]
    recommendations: list[RecommendationOut]

    model_config = {"from_attributes": True}


# --- Stage C13 — Forecasting ------------------------------------------


class DailyForecastOut(BaseModel):
    forecast_date: date
    point: Decimal
    low: Decimal
    high: Decimal

    model_config = {"from_attributes": True}


class ForecastResultOut(BaseModel):
    # True when there's under app/analytics/forecasting.py's
    # MIN_HISTORY_DAYS of lookback history — every field below is then
    # meaningless (zeroed) and must not be displayed as a real number.
    insufficient_data: bool
    method: str | None
    history_days_used: int
    daily: list[DailyForecastOut]
    total_point: Decimal
    total_low: Decimal
    total_high: Decimal

    model_config = {"from_attributes": True}


class RevenueForecastOut(BaseModel):
    horizon_days: int
    result: ForecastResultOut

    model_config = {"from_attributes": True}


class ProductDemandForecastOut(BaseModel):
    product_id: uuid.UUID
    name: str
    sku: str | None
    result: ForecastResultOut
    current_stock: int
    # A simple starting suggestion (confidence band's high end minus
    # current stock) — does not model supplier lead time or safety stock.
    suggested_reorder_quantity: int
    days_of_cover_at_forecast_rate: Decimal | None

    model_config = {"from_attributes": True}


class ForecastOut(BaseModel):
    horizon_days: int
    revenue: RevenueForecastOut
    products: list[ProductDemandForecastOut]
    products_excluded_insufficient_data: int

    model_config = {"from_attributes": True}
