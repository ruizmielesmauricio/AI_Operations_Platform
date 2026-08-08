import uuid

from pydantic import BaseModel, Field


class BusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    template: str = Field(default="bicycle_shop", max_length=64)
    timezone: str = Field(default="Europe/Dublin", max_length=64)


class BusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    template: str
    timezone: str
    role: str
    # None = a standalone/primary shop; set = this is a branch of that
    # parent business, billed separately at the discounted branch price
    # (app/billing/service.py::start_checkout) rather than the standard
    # one. Lets the frontend show a branch distinctly and only offer
    # "Add a branch" on a standalone shop.
    parent_business_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}
