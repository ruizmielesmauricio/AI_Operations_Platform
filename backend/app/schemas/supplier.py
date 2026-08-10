import uuid
from decimal import Decimal

from pydantic import BaseModel


class SupplierOut(BaseModel):
    id: uuid.UUID
    name: str
    contact_info: str | None
    status: str

    model_config = {"from_attributes": True}


class SupplierCreate(BaseModel):
    name: str
    contact_info: str | None = None


class SupplierCreateResponse(BaseModel):
    supplier: SupplierOut
    # True when this call actually created a new row; False when it
    # matched an existing active supplier by normalized name instead
    # (see app/application/suppliers.py::create_supplier).
    created: bool


class SupplierUpdate(BaseModel):
    name: str | None = None
    contact_info: str | None = None


class SupplierMergeRequest(BaseModel):
    target_supplier_id: uuid.UUID


class ProductSupplierCorrection(BaseModel):
    product_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_sku: str | None = None
    lead_time_days: Decimal | None = None


class ProductSupplierOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_sku: str | None
    lead_time_days: Decimal | None

    model_config = {"from_attributes": True}


class SupplierSpendRowOut(BaseModel):
    supplier_id: uuid.UUID | None
    supplier_name: str
    spend: Decimal
    product_count: int
    purchase_count: int

    model_config = {"from_attributes": True}


class SupplierAnalyticsOut(BaseModel):
    start: str
    end: str
    rows: list[SupplierSpendRowOut]
    unknown_supplier_share_pct: Decimal | None

    model_config = {"from_attributes": True}
