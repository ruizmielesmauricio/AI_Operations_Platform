import uuid
from datetime import datetime
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
    revenue_with_known_cost: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal | None
    cost_data_coverage_pct: Decimal | None

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

    model_config = {"from_attributes": True}


class DeadStockOut(BaseModel):
    product_id: uuid.UUID
    name: str
    stock_on_hand: int

    model_config = {"from_attributes": True}


class InventoryValueOut(BaseModel):
    value_at_cost: Decimal
    products_missing_cost: int

    model_config = {"from_attributes": True}


class RetailOperationsOut(BaseModel):
    period: PeriodOut
    top_sellers: list[ProductSalesOut]
    stock_cover: list[StockCoverOut]
    dead_stock: list[DeadStockOut]
    inventory_value: InventoryValueOut
    sell_through_rate: Decimal | None

    model_config = {"from_attributes": True}
