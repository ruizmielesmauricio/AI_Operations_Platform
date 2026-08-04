"""Paid-access gate for routes that require an active subscription.

Not yet applied to anything — Stages B-E (the actual paid product) haven't
been built. When a route needs to be paid-only, depend on
require_active_subscription the same way tenant-scoped routes depend on
app.security.tenant.get_current_membership (which this itself builds on).
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.repositories.subscription import SubscriptionRepository
from app.security.tenant import get_current_membership


def require_active_subscription(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Membership:
    subscription = SubscriptionRepository(db).get_by_business_id(membership.business_id)
    if subscription is None or subscription.status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required for this business",
        )
    return membership
