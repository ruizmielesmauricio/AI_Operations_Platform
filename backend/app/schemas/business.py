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
    # Profile fields — descriptive contact/location record-keeping only,
    # not a second login (see app/models/business.py). All optional; most
    # useful once an account has more than one location and the shop name
    # alone doesn't distinguish them.
    manager_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    location_label: str | None = None
    address_line1: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None

    model_config = {"from_attributes": True}


class BusinessProfileUpdate(BaseModel):
    """PATCH /businesses/{id} — every field optional so a caller only
    sends what actually changed; a field left out is left untouched
    (repositories/business.py::update_business_profile only writes keys
    that were actually set, via model_dump(exclude_unset=True) — an
    explicit null still clears a field, omitting it entirely does not).
    """

    manager_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=64)
    location_label: str | None = Field(default=None, max_length=255)
    address_line1: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=128)
    timezone: str | None = Field(default=None, max_length=64)
