from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.billing import service
from app.billing.exceptions import InvalidWebhookSignature
from app.models.membership import Membership
from app.repositories.subscription import SubscriptionRepository
from app.schemas.billing import (
    CheckoutSessionResponse,
    PortalSessionResponse,
    SubscriptionStatusResponse,
)
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

# Tenant-scoped: business_id comes from the URL and is verified by
# get_current_membership (PR-6.1/6.2), never trusted from a request body.
router = APIRouter(prefix="/businesses/{business_id}/billing", tags=["billing"])

# Stripe calls this directly at a fixed URL — it has no user session to
# authenticate, and is never tenant-scoped. The Stripe signature check in
# service.handle_webhook_event is its only authentication.
webhook_router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout-session", response_model=CheckoutSessionResponse)
def create_checkout_session(
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> CheckoutSessionResponse:
    # Starting a real payment flow is an owner-only action (Notification
    # Centre permissions batch) — matches the same role check already on
    # employee-seat and branch/delete-business routes.
    if membership.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can manage billing")
    checkout_url = service.start_checkout(
        db=db, business_id=membership.business_id, business_email=current_user.email
    )
    return CheckoutSessionResponse(checkout_url=checkout_url)


@router.post("/portal-session", response_model=PortalSessionResponse)
def create_portal_session(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> PortalSessionResponse:
    if membership.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can manage billing")
    subscription = SubscriptionRepository(db).get_by_business_id(membership.business_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="No subscription for this business")
    portal_url = service.start_portal_session(stripe_customer_id=subscription.stripe_customer_id)
    return PortalSessionResponse(portal_url=portal_url)


@router.get("/subscription", response_model=SubscriptionStatusResponse)
def get_subscription_status(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> SubscriptionStatusResponse:
    subscription = SubscriptionRepository(db).get_by_business_id(membership.business_id)
    return SubscriptionStatusResponse(
        status=subscription.status if subscription else None,
        current_period_end=subscription.current_period_end if subscription else None,
    )


@webhook_router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    payload = await request.body()
    signature_header = request.headers.get("stripe-signature", "")
    try:
        service.handle_webhook_event(db, payload, signature_header)
    except InvalidWebhookSignature:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    return {"status": "ok"}
