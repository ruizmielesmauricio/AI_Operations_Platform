import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.billing.service import cancel_subscription
from app.geocoding.service import suggest_addresses
from app.models.business import Business
from app.models.membership import Membership
from app.repositories.business import (
    BusinessLimitReached,
    NotBusinessOwner,
    create_branch_business,
    create_business_with_owner,
    list_businesses_for_user,
    soft_delete_business,
    update_business_profile,
)
from app.schemas.business import (
    AddressSuggestionOut,
    BusinessCreate,
    BusinessOut,
    BusinessProfileUpdate,
)
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses", tags=["businesses"])


def _to_business_out(business: Business, *, role: str) -> BusinessOut:
    # One place listing every Business field BusinessOut needs — every
    # route below calls this instead of constructing BusinessOut inline,
    # specifically because that pattern already caused a real bug once
    # (parent_business_id silently defaulting to None in two routes that
    # forgot to pass it through). A field added to the model only needs
    # updating here, not at every call site.
    return BusinessOut(
        id=business.id,
        name=business.name,
        template=business.template,
        timezone=business.timezone,
        role=role,
        parent_business_id=business.parent_business_id,
        manager_name=business.manager_name,
        contact_email=business.contact_email,
        contact_phone=business.contact_phone,
        location_label=business.location_label,
        address_line1=business.address_line1,
        city=business.city,
        postal_code=business.postal_code,
        country=business.country,
        deleted_at=business.deleted_at,
    )


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
    return _to_business_out(business, role="owner")


@router.get("", response_model=list[BusinessOut])
def list_my_businesses(
    # Opt-in, defaults False — every existing caller (dashboard/uploads/
    # reports business selectors) gets exactly today's behavior unchanged.
    # Only the "Company Profile" list (frontend/app/onboarding/page.tsx)
    # passes true, to show archived businesses (status "Deleted") for
    # visibility/history rather than hiding them entirely.
    include_deleted: bool = Query(default=False),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> list[BusinessOut]:
    rows = list_businesses_for_user(db, user_id=current_user.id, include_deleted=include_deleted)
    return [_to_business_out(business, role=membership.role) for business, membership in rows]


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
    return _to_business_out(business, role=membership.role)


@router.patch("/{business_id}", response_model=BusinessOut)
def update_business(
    business_id: uuid.UUID,
    payload: BusinessProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BusinessOut:
    # Deliberately get_current_membership, not an owner-only check — this
    # is descriptive contact/location record-keeping (manager name,
    # address, phone, timezone...), not a financial or destructive action
    # like delete or add-a-branch, so any member of the business may edit
    # it.
    business = db.get(Business, business_id)
    if business is None or business.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    # exclude_unset, not exclude_none — a field explicitly sent as null
    # clears it; a field left out of the request body entirely is left
    # untouched. Matters here specifically because every field is
    # optional, so "not sent" and "sent as empty" need to mean different
    # things.
    updates = payload.model_dump(exclude_unset=True)
    business = update_business_profile(db, business=business, updates=updates)
    return _to_business_out(business, role=membership.role)


@router.get("/{business_id}/address-suggestions", response_model=list[AddressSuggestionOut])
def get_address_suggestions(
    business_id: uuid.UUID,
    text: str = Query(default="", max_length=255),
    membership: Membership = Depends(get_current_membership),
) -> list[AddressSuggestionOut]:
    # Live, as-you-type suggestions — deliberately does not save anything
    # itself (frontend/app/onboarding/[id]/page.tsx applies whichever one
    # the owner clicks directly into the profile form, which still needs
    # the normal PATCH above to actually save, same as any other edit).
    # business_id in the URL exists only for the tenant-scoping gate
    # (get_current_membership) and consistency with every other route
    # here — the suggestions themselves have nothing business-specific
    # about them. GET + a query param, not POST + a body: this is an
    # idempotent lookup, matching every other read-only route's shape.
    results = suggest_addresses(text)
    return [AddressSuggestionOut.model_validate(r) for r in results]


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
    return _to_business_out(branch, role="owner")


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
