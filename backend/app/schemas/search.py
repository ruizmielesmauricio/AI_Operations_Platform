import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ProductSearchResultOut(BaseModel):
    id: uuid.UUID
    name: str
    sku: str | None
    category_name: str | None
    current_stock: int | None


class SaleSearchResultOut(BaseModel):
    id: uuid.UUID
    sold_at: datetime
    product_id: uuid.UUID | None
    product_name: str | None
    sku: str | None
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    order_reference: str | None


class PurchaseSearchResultOut(BaseModel):
    id: uuid.UUID
    event_date: date | None
    product_id: uuid.UUID | None
    product_name: str | None
    sku: str | None
    supplier_name: str | None
    quantity_delta: int
    purchase_reference: str | None


class SupplierSearchResultOut(BaseModel):
    id: uuid.UUID
    name: str
    contact_info: str | None
    status: str


class RepairSearchResultOut(BaseModel):
    id: uuid.UUID
    completed_at: datetime | None
    description: str | None
    repair_reference: str | None
    price_charged: Decimal | None


class SearchResultOut(BaseModel):
    query: str
    products: list[ProductSearchResultOut]
    sales: list[SaleSearchResultOut]
    purchases: list[PurchaseSearchResultOut]
    suppliers: list[SupplierSearchResultOut]
    repairs: list[RepairSearchResultOut]
