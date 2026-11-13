"""Access gate for routes that need a paying (or pilot) business.

A business has access when EITHER its Stripe subscription is active OR it
is inside a free pilot window (Business.pilot_access_until in the future —
pilot testers don't pay, decision 2026-11-12). Every paid-only route
depends on require_active_subscription the same way tenant-scoped routes
depend on app.security.tenant.get_current_membership (which this builds on).
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.billing.pilot import pilot_access_active
from app.models.business import Business
from app.models.membership import Membership
from app.repositories.subscription import SubscriptionRepository
from app.security.tenant import get_current_membership

__all__ = ["business_access", "pilot_access_active", "require_active_subscription"]

AccessKind = Literal["subscription", "pilot"]


def business_access(db: Session, business_id: uuid.UUID, now: datetime | None = None) -> AccessKind | None:
    """Why this business may use paid features, or None if it may not. A
    paid subscription wins over a pilot when both apply."""
    subscription = SubscriptionRepository(db).get_by_business_id(business_id)
    if subscription is not None and subscription.status == "active":
        return "subscription"
    if pilot_access_active(db.get(Business, business_id), now):
        return "pilot"
    return None


def require_active_subscription(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Membership:
    if business_access(db, membership.business_id) is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An active subscription is required for this business",
        )
    return membership
