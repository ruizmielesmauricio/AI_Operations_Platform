import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.membership import Membership


class BusinessLimitReached(Exception):
    """Raised when a user tries to create a second standalone (non-branch)
    business — this codebase's convention is a dedicated exceptions.py per
    multi-file feature module (see app/imports/exceptions.py, app/billing/
    exceptions.py); business.py is a single repository file with no such
    module around it, so this lives next to the function that raises it
    instead of in a new shared file. The API layer (app/api/businesses.py)
    maps this to a 409, per CLAUDE.md's "thin route handlers; logic in
    domain/ or analytics/" — this module owns the rule, not the HTTP
    status it becomes.
    """


class NotBusinessOwner(Exception):
    """Raised when a caller tries to add a branch under a parent business
    they don't own — distinct from BusinessLimitReached (this is an
    authorization failure, not a quota one). The API layer maps this to
    a 403.
    """


def count_owned_standalone_businesses(db: Session, *, user_id: str) -> int:
    """How many non-deleted, non-branch businesses this user owns — the
    exact count the one-shop-per-account limit checks. Deliberately
    excludes branches (parent_business_id IS NOT NULL): a branch consumes
    a paid branch slot, not the one free standalone shop, per the
    confirmed design (schema groundwork only in this pass — no route can
    create a branch yet, but the limit check already understands the
    distinction so it doesn't need revisiting when that route exists).
    """
    return (
        db.query(Business)
        .join(Membership, Membership.business_id == Business.id)
        .filter(
            Membership.user_id == user_id,
            Membership.role == "owner",
            Business.parent_business_id.is_(None),
            Business.deleted_at.is_(None),
        )
        .count()
    )


def create_business_with_owner(
    db: Session, *, name: str, template: str, timezone: str, owner_user_id: str
) -> Business:
    """Creates the business and its owner membership in one transaction —
    a business must never exist without at least one member (PR-1.1).

    Raises BusinessLimitReached before creating anything if the user
    already owns a standalone business — checked first so a rejected
    request never partially creates a row.
    """
    if count_owned_standalone_businesses(db, user_id=owner_user_id) >= 1:
        raise BusinessLimitReached(f"User {owner_user_id} already owns a standalone business")

    business = Business(name=name, template=template, timezone=timezone)
    db.add(business)
    db.flush()
    db.add(Membership(business_id=business.id, user_id=owner_user_id, role="owner"))
    db.commit()
    db.refresh(business)
    return business


def create_branch_business(
    db: Session,
    *,
    name: str,
    template: str,
    timezone: str,
    owner_user_id: str,
    parent_business_id: uuid.UUID,
) -> Business:
    """A branch is exempt from the one-standalone-shop limit — count_owned_
    standalone_businesses already excludes parent_business_id IS NOT NULL
    rows, so this never raises BusinessLimitReached. The real gate here
    is ownership of the parent, not a pre-purchased quantity: each branch
    pays for itself via its own separate Stripe subscription at the
    discounted branch price (app/billing/service.py::start_checkout,
    keyed off this row's own parent_business_id), started right after
    this creates the row — the same "created unsubscribed, then Subscribe"
    flow every standalone business already goes through, not a new one.
    """
    parent_membership = (
        db.query(Membership)
        .filter(
            Membership.business_id == parent_business_id,
            Membership.user_id == owner_user_id,
            Membership.role == "owner",
        )
        .first()
    )
    if parent_membership is None:
        raise NotBusinessOwner(f"User {owner_user_id} is not the owner of business {parent_business_id}")

    branch = Business(name=name, template=template, timezone=timezone, parent_business_id=parent_business_id)
    db.add(branch)
    db.flush()
    db.add(Membership(business_id=branch.id, user_id=owner_user_id, role="owner"))
    db.commit()
    db.refresh(branch)
    return branch


def list_businesses_for_user(
    db: Session, *, user_id: str, include_deleted: bool = False
) -> list[tuple[Business, Membership]]:
    # include_deleted is opt-in and defaults False specifically so every
    # existing caller (dashboard/uploads/reports business selectors, the
    # onboarding page's own create/delete flow) keeps its current
    # behavior unchanged — archived businesses stay invisible everywhere
    # except the one place that explicitly asks to see them (the "Company
    # Profile" list, which shows a Deleted status for visibility/history
    # rather than actionable management).
    query = db.query(Business, Membership).join(Membership, Membership.business_id == Business.id).filter(
        Membership.user_id == user_id
    )
    if not include_deleted:
        query = query.filter(Business.deleted_at.is_(None))
    return query.all()


def soft_delete_business(db: Session, *, business: Business) -> Business:
    """Archives a business — sets deleted_at, nothing else. Every other
    row that references this business (products, sales, uploads, its own
    Subscription, audit log, ...) is left exactly as it is: confirmed
    with the user this is archive, not destroy, consistent with this
    codebase's audit-log-conscious posture and with the real constraint
    that none of the ~20+ business_id foreign keys in this schema have
    ON DELETE CASCADE — a hard delete would fail outright the moment any
    child row exists.

    Caller (app/api/businesses.py) is responsible for the owner-role
    authorization check (already has the authenticated Membership in
    hand from get_current_membership, no need to re-query it here) and
    for cancelling any active Stripe subscription via
    app/billing/service.py::cancel_subscription — kept out of this
    function so a repository module never needs to import the billing
    module's Stripe-touching code.
    """
    business.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(business)
    return business


# Every field a PATCH /businesses/{id} call is allowed to touch — never
# name/template/parent_business_id/deleted_at, which have their own,
# more carefully-gated mutation paths elsewhere (creation, the branch
# route, soft-delete). Kept as an explicit whitelist here as a second,
# defensive check independent of app/schemas/business.py::
# BusinessProfileUpdate's own field list, in case a future caller ever
# passes something wider than that schema intends.
_PROFILE_FIELDS = frozenset(
    {
        "manager_name",
        "contact_email",
        "contact_phone",
        "location_label",
        "address_line1",
        "city",
        "postal_code",
        "country",
        "timezone",
    }
)


def update_business_profile(db: Session, *, business: Business, updates: dict) -> Business:
    """Applies a partial update to a business's descriptive profile —
    manager name, contact details, address, timezone. Deliberately not a
    second login/account (confirmed with the user): these are
    record-keeping fields only, most useful once an account has more
    than one location and the shop `name` alone doesn't distinguish them.

    `updates` is expected to already be the caller's
    `model_dump(exclude_unset=True)` — a key that's present with value
    None clears that field; a key left out entirely is left untouched.
    Any key outside `_PROFILE_FIELDS` is silently ignored rather than
    raising, since the schema itself already constrains what can arrive
    here; this is a second line of defence, not the primary gate.
    """
    for field, value in updates.items():
        if field not in _PROFILE_FIELDS:
            continue
        setattr(business, field, value)
    db.commit()
    db.refresh(business)
    return business
