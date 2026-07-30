from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.billing import service
from app.billing.exceptions import InvalidWebhookSignature
from app.repositories.subscription import SubscriptionRepository
from app.schemas.billing import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PortalSessionRequest,
    PortalSessionResponse,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout-session", response_model=CheckoutSessionResponse)
def create_checkout_session(body: CheckoutSessionRequest) -> CheckoutSessionResponse:
    checkout_url = service.start_checkout(
        business_id=body.business_id, business_email=body.business_email
    )
    return CheckoutSessionResponse(checkout_url=checkout_url)


@router.post("/portal-session", response_model=PortalSessionResponse)
def create_portal_session(
    body: PortalSessionRequest, db: Session = Depends(get_db)
) -> PortalSessionResponse:
    subscription = SubscriptionRepository(db).get_by_business_id(body.business_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="No subscription for this business")
    portal_url = service.start_portal_session(stripe_customer_id=subscription.stripe_customer_id)
    return PortalSessionResponse(portal_url=portal_url)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature", "")
    try:
        service.handle_webhook_event(db, payload, signature_header)
    except InvalidWebhookSignature:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    return {"status": "ok"}
