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

    model_config = {"from_attributes": True}
