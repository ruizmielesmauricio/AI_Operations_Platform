from datetime import datetime

from pydantic import BaseModel


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    status: str | None
    current_period_end: datetime | None
    # Why the business may use paid features: "subscription", "pilot" (free
    # pilot window, app/billing/access.py), or None. The frontend gates on
    # this, not on status, so a pilot business is never shown as unpaid.
    access: str | None = None
    pilot_access_until: datetime | None = None
