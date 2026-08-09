import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class SaleTransactionOut(BaseModel):
    id: uuid.UUID
    sold_at: datetime
    product_id: uuid.UUID | None
    product_name: str | None
    category_name: str | None
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    order_reference: str | None
    import_record_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class PurchaseTransactionOut(BaseModel):
    id: uuid.UUID
    event_date: date | None
    product_id: uuid.UUID | None
    product_name: str | None
    category_name: str | None
    quantity_delta: int
    unit_cost: Decimal | None
    purchase_reference: str | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    import_record_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class RepairTransactionOut(BaseModel):
    id: uuid.UUID
    completed_at: datetime | None
    description: str | None
    price_charged: Decimal | None
    labour_cost: Decimal | None
    tax_amount: Decimal | None
    repair_reference: str | None
    import_record_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class PaginatedSaleTransactionsOut(BaseModel):
    items: list[SaleTransactionOut]
    total: int
    limit: int
    offset: int

    model_config = {"from_attributes": True}


class PaginatedPurchaseTransactionsOut(BaseModel):
    items: list[PurchaseTransactionOut]
    total: int
    limit: int
    offset: int

    model_config = {"from_attributes": True}


class PaginatedRepairTransactionsOut(BaseModel):
    items: list[RepairTransactionOut]
    total: int
    limit: int
    offset: int

    model_config = {"from_attributes": True}
