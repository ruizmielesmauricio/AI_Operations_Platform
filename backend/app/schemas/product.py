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
    recommendation: ThresholdRecommendationOut
    insufficient_data: bool

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
