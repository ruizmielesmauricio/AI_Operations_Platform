import uuid
from decimal import Decimal

from pydantic import BaseModel


class ThresholdRecommendationOut(BaseModel):
    recommended_threshold_days: Decimal
    basis: str
    lead_time_days: Decimal | None
    safety_buffer_days: Decimal
    current_threshold_days: Decimal | None

    model_config = {"from_attributes": True}


class ProductThresholdOut(BaseModel):
    product_id: uuid.UUID
    name: str
    sku: str | None
    category_id: uuid.UUID | None
    category_name: str | None
    stock_on_hand: int
    units_sold_in_period: int
    cover_days: Decimal | None
    effective_threshold_days: Decimal
    product_threshold_days: Decimal | None
    # "manual" | "orla_recommended" | None — see Product.low_stock_
    # threshold_source's own docstring. Powers the Product Reorder Rules
    # table's "Setting" column (Category default / Product custom / ORLA
    # recommended / System default).
    product_threshold_source: str | None
    category_threshold_days: Decimal | None
    recommendation: ThresholdRecommendationOut
    insufficient_data: bool

    model_config = {"from_attributes": True}


class ProductThresholdSaveOut(BaseModel):
    """The minimal, real body PATCH .../products/{id}/threshold now
    returns — 200, not 204 (see app/application/products.py::
    update_product_threshold's docstring for why 204 was the actual
    save-failure bug). Deliberately not the full ProductThresholdOut
    shape: recomputing stock/sales/recommendation context on every save
    is unnecessary work the frontend doesn't use — it just reloads the
    whole list after a successful save."""

    product_id: uuid.UUID
    low_stock_threshold_days: Decimal | None
    low_stock_threshold_source: str | None

    model_config = {"from_attributes": True}


class ProductThresholdUpdate(BaseModel):
    threshold_days: Decimal | None = None
    # True when this PATCH is applying the shown recommendation verbatim
    # (distinct audit action — threshold_recommendation_accepted vs
    # threshold_updated) rather than a manually typed value. The frontend
    # sets this on its "Accept recommendation" button; a manual edit or
    # "dismiss" (which never calls this route at all) leave it False.
    accepted_recommendation: bool = False


class CategoryThresholdUpdate(BaseModel):
    threshold_days: Decimal | None = None
