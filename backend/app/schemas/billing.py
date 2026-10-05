from datetime import datetime

from pydantic import BaseModel


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    status: str | None
    current_period_end: datetime | None
    # A free pilot account (no Stripe) — the UI shows "Complimentary"
    # instead of a Subscribe button.
    is_complimentary: bool = False
