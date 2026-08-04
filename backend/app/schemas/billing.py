from datetime import datetime

from pydantic import BaseModel


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    status: str | None
    current_period_end: datetime | None
