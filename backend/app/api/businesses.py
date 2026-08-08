import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.billing.service import cancel_subscription
from app.models.business import Business
from app.models.membership import Membership
from app.repositories.business import (
    BusinessLimitReached,
    NotBusinessOwner,
    create_branch_business,
    create_business_with_owner,
    list_businesses_for_user,
    soft_delete_business,
)
from app.schemas.business import BusinessCreate, BusinessOut
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses", tags=["businesses"])


@router.post("", response_model=BusinessOut, status_code=status.HTTP_201_CREATED)
def create_business(
    payload: BusinessCreate,
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> BusinessOut:
    try:
        business = create_business_with_owner(
            db,
            name=payload.name,
            template=payload.template,
            timezone=payload.timezone,
            owner_user_id=current_user.id,
        )
    except BusinessLimitReached as exc:
        # One shop per account by default — the second half of this
        # message names a real future upgrade path (paid branches),
        # deliberately deferred (see the plan's own Context section), not
        # a working link yet: honest framing now beats a dead link.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a shop on this account. Delete your existing shop to create a "
            "different one, or contact us about adding a branch.",
        ) from exc
    return BusinessOut(
        id=business.id,
        name=business.name,
        template=business.template,
        timezone=business.timezone,
        role="owner",
        parent_business_id=business.parent_business_id,
    )


@router.get("", response_model=list[BusinessOut])
def list_my_businesses(
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> list[BusinessOut]:
    rows = list_businesses_for_user(db, user_id=current_user.id)
    return [
        BusinessOut(
            id=business.id,
            name=business.name,
            template=business.template,
            timezone=business.timezone,
            role=membership.role,
            parent_business_id=business.parent_business_id,
        )
        for business, membership in rows
    ]


@router.get("/{business_id}", response_model=BusinessOut)
def get_business(
    business_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BusinessOut:
    business = db.get(Business, business_id)
    # A soft-deleted business 404s here too, same as if the row didn't
    # exist at all — list_businesses_for_user already excludes it, so a
    # direct-by-id fetch (e.g. a stale bookmark/tab) must match, not
    # silently keep showing an archived business as if nothing happened.
    if business is None or business.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return BusinessOut(
        id=business.id,
        name=business.name,
        template=business.template,
        timezone=business.timezone,
        role=membership.role,
        parent_business_id=business.parent_business_id,
    )


@router.post("/{business_id}/branches", response_model=BusinessOut, status_code=status.HTTP_201_CREATED)
def create_branch(
    business_id: uuid.UUID,
    payload: BusinessCreate,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BusinessOut:
    # business_id here is the PARENT (the primary shop the branch is
    # added under) — get_current_membership already confirms the caller
    # is a member of it; the owner-role check below and
    # create_branch_business's own re-check are both about *creating*
    # additional shops specifically, not general membership.
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can add a branch"
        )
    try:
        branch = create_branch_business(
            db,
            name=payload.name,
            template=payload.template,
            timezone=payload.timezone,
            owner_user_id=membership.user_id,
            parent_business_id=business_id,
        )
    except NotBusinessOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can add a branch"
        ) from exc
    return BusinessOut(
        id=branch.id,
        name=branch.name,
        template=branch.template,
        timezone=branch.timezone,
        role="owner",
        parent_business_id=branch.parent_business_id,
    )


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business(
    business_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> None:
    # Deliberately get_current_membership, not require_active_subscription
    # — deleting must work even on a lapsed/canceled account (that's
    # arguably the most likely moment someone wants to delete a shop).
    if membership.role != "owner":
        # The first real use of Membership.ROLES anywhere in this
        # codebase — defined since the model was introduced, never
        # enforced until now.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can delete it"
        )
    business = db.get(Business, business_id)
    if business is None or business.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    # Cancel any live Stripe subscription before archiving — a deleted
    # business must not keep being billed. Best-effort ordering: if this
    # raises, the business stays un-deleted rather than silently leaving
    # an orphaned active subscription behind.
    cancel_subscription(db, business_id=business_id)
    soft_delete_business(db, business=business)
