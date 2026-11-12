import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from app.templates import DEFAULT_TEMPLATE_KEY, TEMPLATE_KEYS


def _check_timezone(value: str) -> str:
    # Every period calculation does ZoneInfo(business.timezone): a typo
    # stored here (the field is free text) would make every dashboard,
    # report and forecast for this business fail. Reject it at the door.
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown timezone. Use an IANA name such as Europe/Dublin.") from exc
    return value


class BusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    template: str = Field(default=DEFAULT_TEMPLATE_KEY, max_length=64)
    timezone: str = Field(default="Europe/Dublin", max_length=64)

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        return _check_timezone(value)

    @field_validator("template")
    @classmethod
    def _known_template(cls, value: str) -> str:
        # Previously any string was accepted and stored, silently creating a
        # business type nothing in the app knew how to serve.
        if value not in TEMPLATE_KEYS:
            raise ValueError(f"Unknown business type. Choose one of: {', '.join(sorted(TEMPLATE_KEYS))}")
        return value


class BusinessTemplateOut(BaseModel):
    key: str
    label: str
    description: str
    group: str
    supports_repairs: bool


class BusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    template: str
    template_label: str = ""
    # Whether this business's type tracks repairs/service jobs — the
    # frontend hides the repairs upload type, Workshop Performance and the
    # repairs transactions tab when False.
    supports_repairs: bool = False
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
    # Free pilot window end (app/billing/access.py); None = not a pilot.
    pilot_access_until: datetime | None = None
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

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str | None) -> str | None:
        return _check_timezone(value) if value is not None else None
