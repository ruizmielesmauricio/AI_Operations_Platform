import uuid
from datetime import datetime

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
    manager_first_name: str | None = None
    manager_surname: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    location_label: str | None = None
    address_line1: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None
    # True once a logo has been uploaded (Business.logo_content_type is
    # non-null) — tells the frontend whether to render the
    # GET /businesses/{id}/logo <img> at all, rather than guaranteeing a
    # 404 request for every logo-less business.
    has_logo: bool = False
    # Frontend cache-buster for the logo <img> src (?v=updated_at) — a
    # re-upload overwrites the same R2 key/URL, so without this the
    # browser would keep showing the old cached image. Reused rather than
    # adding a dedicated logo-uploaded-at column: any profile field's
    # onupdate already bumps it, and a logo upload/delete is itself a
    # profile write.
    updated_at: datetime
    # Only ever non-null when the caller opted into GET /businesses?
    # include_deleted=true (frontend/app/onboarding/page.tsx's "Company
    # Profile" list, which shows every business including archived ones
    # for visibility) — every other caller (dashboard/uploads/reports
    # business selectors) never sees a deleted business at all, so this
    # is always None there.
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}


class AddressSuggestionOut(BaseModel):
    formatted_address: str
    address_line1: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None
    timezone: str | None = None

    model_config = {"from_attributes": True}


class BusinessProfileUpdate(BaseModel):
    """PATCH /businesses/{id} — every field optional so a caller only
    sends what actually changed; a field left out is left untouched
    (repositories/business.py::update_business_profile only writes keys
    that were actually set, via model_dump(exclude_unset=True) — an
    explicit null still clears a field, omitting it entirely does not).
    """

    manager_first_name: str | None = Field(default=None, max_length=128)
    manager_surname: str | None = Field(default=None, max_length=128)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=64)
    location_label: str | None = Field(default=None, max_length=255)
    address_line1: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=128)
    timezone: str | None = Field(default=None, max_length=64)
