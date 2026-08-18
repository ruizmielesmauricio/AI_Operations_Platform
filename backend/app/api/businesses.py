import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.employee_seats import EmployeeSeatNotFound, get_own_employee_seat, update_own_employee_profile
from app.application.members import list_business_members
from app.billing.service import cancel_subscription
from app.geocoding.service import suggest_addresses
from app.imports import r2_client
from app.models.business import Business
from app.models.membership import Membership
from app.repositories.audit_log import record_audit_event
from app.repositories.business import (
    BusinessLimitReached,
    ExistingMemberCannotCreateBusiness,
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
from app.schemas.employee_seat import EmployeeSeatOut, SelfProfileUpdate
from app.schemas.member import MemberOut
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses", tags=["businesses"])

# A logo isn't a data file the import pipeline reasons about — small,
# synchronously-validated, and written straight through the backend
# rather than via a presigned browser PUT (see app/imports/r2_client.py's
# put_object_bytes docstring). One fixed key per business: a re-upload
# always overwrites it, so there's never an orphaned old logo in R2 to
# separately track or clean up.
_ALLOWED_LOGO_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_LOGO_SIZE_BYTES = 5 * 1024 * 1024


def _logo_storage_key(business_id: uuid.UUID) -> str:
    return f"logos/{business_id}/logo"


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
        manager_first_name=business.manager_first_name,
        manager_surname=business.manager_surname,
        contact_email=business.contact_email,
        contact_phone=business.contact_phone,
        location_label=business.location_label,
        address_line1=business.address_line1,
        city=business.city,
        postal_code=business.postal_code,
        country=business.country,
        has_logo=business.logo_content_type is not None,
        updated_at=business.updated_at,
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
    except ExistingMemberCannotCreateBusiness as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is already assigned to a business. Ask its owner to update your access instead.",
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


@router.get("/{business_id}/members", response_model=list[MemberOut])
def list_members(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    # Any member can view — display-only (name + role), not the more
    # sensitive employee-seat detail (email, Stripe ids) the owner-only
    # GET .../employee-seats route returns for actual management.
    members = list_business_members(db, membership.business_id)
    return [MemberOut.model_validate(m) for m in members]


@router.get("/{business_id}/me", response_model=EmployeeSeatOut)
def get_my_employee_profile(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> EmployeeSeatOut:
    # Staff self-profile (Company Profile permissions batch) — the
    # owner's own "profile" is the Business record's manager_first_name/
    # manager_surname fields instead, edited through the owner-only
    # PATCH /businesses/{id} above; an owner has no EmployeeSeat row to
    # return here at all.
    try:
        seat = get_own_employee_seat(db, business_id=membership.business_id, user_id=membership.user_id)
    except EmployeeSeatNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile found for this account"
        ) from exc
    return EmployeeSeatOut.from_seat(seat)


@router.patch("/{business_id}/me", response_model=EmployeeSeatOut)
def update_my_employee_profile(
    payload: SelfProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> EmployeeSeatOut:
    # Deliberately no role/status/email in SelfProfileUpdate — a staff
    # member editing themselves can only ever change first_name/surname/
    # address, all the way down through update_own_employee_profile and
    # EmployeeSeatRepository.update_self_profile.
    try:
        seat = update_own_employee_profile(
            db,
            business_id=membership.business_id,
            user_id=membership.user_id,
            first_name=payload.first_name,
            surname=payload.surname,
            address_line1=payload.address_line1,
            city=payload.city,
            postal_code=payload.postal_code,
            country=payload.country,
        )
    except EmployeeSeatNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile found for this account"
        ) from exc
    return EmployeeSeatOut.from_seat(seat)


@router.patch("/{business_id}", response_model=BusinessOut)
def update_business(
    business_id: uuid.UUID,
    payload: BusinessProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BusinessOut:
    # Owner-only (Company Profile permissions batch) — company/branch
    # profile data was previously editable by any member; product rule is
    # now "only owners can change anything related to the company or
    # branches." Checked before any audit event is written, so a rejected
    # staff attempt leaves no trace (a rejected action never happened).
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can edit the company profile"
        )
    business = db.get(Business, business_id)
    if business is None or business.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    # exclude_unset, not exclude_none — a field explicitly sent as null
    # clears it; a field left out of the request body entirely is left
    # untouched. Matters here specifically because every field is
    # optional, so "not sent" and "sent as empty" need to mean different
    # things.
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        # Written before update_business_profile (rather than after) so it
        # lands in that same commit (PR-6.5) — field *names* only, never
        # the values themselves, which can carry contact/location PII
        # this log has no reason to retain.
        record_audit_event(
            db,
            business_id=business.id,
            user_id=membership.user_id,
            action="business_profile_updated",
            target_type="business",
            target_id=str(business.id),
            metadata={"fields_changed": sorted(updates.keys())},
        )
    business = update_business_profile(db, business=business, updates=updates)
    return _to_business_out(business, role=membership.role)


@router.post("/{business_id}/logo", response_model=BusinessOut)
async def upload_logo(
    business_id: uuid.UUID,
    file: UploadFile = File(...),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BusinessOut:
    # Owner-only, same gate as PATCH /{business_id} above — the company
    # logo is company-profile data.
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can change the company logo"
        )
    business = db.get(Business, business_id)
    if business is None or business.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    if file.content_type not in _ALLOWED_LOGO_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Logo must be a PNG, JPEG, or WEBP image",
        )
    data = await file.read()
    if len(data) > _MAX_LOGO_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Logo file is too large (5MB limit)",
        )
    r2_client.put_object_bytes(storage_key=_logo_storage_key(business_id), data=data, content_type=file.content_type)
    business.logo_content_type = file.content_type
    db.commit()
    db.refresh(business)
    return _to_business_out(business, role=membership.role)


@router.get("/{business_id}/logo")
def get_logo(business_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    # Deliberately PUBLIC — no membership/auth dependency. A plain <img>
    # tag can't send this app's JWT Authorization header, and every other
    # route here requires one; confirmed with the user that a shop logo
    # isn't sensitive like sales/financial data, so this is a narrow,
    # intentional exception to the usual "every route is tenant-scoped
    # and authenticated" posture rather than something slipped in
    # quietly. Only the logo bytes are exposed — nothing else about the
    # business.
    business = db.get(Business, business_id)
    if business is None or business.deleted_at is not None or business.logo_content_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo set for this business")
    data = r2_client.download_object(storage_key=_logo_storage_key(business_id))
    return Response(
        content=data,
        media_type=business.logo_content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.delete("/{business_id}/logo", response_model=BusinessOut)
def delete_logo(
    business_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BusinessOut:
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can change the company logo"
        )
    business = db.get(Business, business_id)
    if business is None or business.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    if business.logo_content_type is not None:
        r2_client.delete_object(storage_key=_logo_storage_key(business_id))
        business.logo_content_type = None
        db.commit()
        db.refresh(business)
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
    subscription_canceled = cancel_subscription(db, business_id=business_id)
    # Written before soft_delete_business (rather than after) so both
    # entries land in that same commit (PR-6.5) — soft_delete_business is
    # the one that actually commits the transaction below.
    if subscription_canceled:
        record_audit_event(
            db,
            business_id=business.id,
            user_id=membership.user_id,
            action="subscription_canceled",
            target_type="business",
            target_id=str(business.id),
        )
    record_audit_event(
        db,
        business_id=business.id,
        user_id=membership.user_id,
        action="branch_deleted" if business.parent_business_id else "business_deleted",
        target_type="business",
        target_id=str(business.id),
    )
    soft_delete_business(db, business=business)
