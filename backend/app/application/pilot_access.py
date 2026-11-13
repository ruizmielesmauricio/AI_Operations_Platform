"""Free pilot access — granting and ending it (decision 2026-11-12: pilot
testers don't pay).

Operator-only: there is deliberately no HTTP route for this. A pilot is
granted with scripts/pilot_access.py, run by whoever operates the
platform. A business-facing endpoint would let any owner give themselves
free access.

A grant covers the business AND every existing branch of it; a branch
created later inherits the parent's window (app/api/businesses.py::
create_branch). Seats added during the pilot are free too
(app/application/employee_seats.py::add_employee).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.notifications import CATEGORY_BILLING, SEVERITY_SUCCESS, SEVERITY_WARNING, notify
from app.models.business import Business
from app.models.membership import Membership
from app.models.user import User
from app.repositories.audit_log import record_audit_event

OPERATOR_ACTOR = "platform-operator"
MAX_PILOT_DAYS = 366


class PilotAccessError(Exception):
    pass


def _family(db: Session, business_id: uuid.UUID) -> list[Business]:
    business = db.get(Business, business_id)
    if business is None or business.deleted_at is not None:
        raise PilotAccessError(f"No active business with id {business_id}")
    root = db.get(Business, business.parent_business_id) if business.parent_business_id else business
    branches = db.scalars(
        select(Business).where(Business.parent_business_id == root.id, Business.deleted_at.is_(None))
    ).all()
    return [root, *branches]


def grant_pilot_access(
    db: Session, *, business_id: uuid.UUID, days: int, now: datetime | None = None
) -> datetime:
    """Gives the business (and its branches) free access for `days` days
    from now. Re-granting replaces the end date. Returns the end date."""
    if not 1 <= days <= MAX_PILOT_DAYS:
        raise PilotAccessError(f"days must be between 1 and {MAX_PILOT_DAYS}")
    until = (now or datetime.now(timezone.utc)) + timedelta(days=days)
    family = _family(db, business_id)
    for business in family:
        business.pilot_access_until = until
        record_audit_event(
            db,
            business_id=business.id,
            user_id=OPERATOR_ACTOR,
            action="pilot_access_granted",
            target_type="business",
            target_id=str(business.id),
            metadata={"until": until.isoformat(), "days": days},
        )
    root = family[0]
    notify(
        db,
        business_id=root.id,
        category=CATEGORY_BILLING,
        type_key="pilot_access",
        severity=SEVERITY_SUCCESS,
        title="Free pilot access is active",
        body=(
            f"You're part of the ORLA pilot: everything is free until {until:%d %b %Y}, "
            "including branches and staff seats. No payment details needed."
        ),
        action_label="Upload data",
        action_url="/uploads",
        visible_to_role="owner",
        dedup_key=f"pilot_access:{root.id}",
    )
    db.commit()
    return until


def end_pilot_access(db: Session, *, business_id: uuid.UUID) -> None:
    family = _family(db, business_id)
    for business in family:
        business.pilot_access_until = None
        record_audit_event(
            db,
            business_id=business.id,
            user_id=OPERATOR_ACTOR,
            action="pilot_access_ended",
            target_type="business",
            target_id=str(business.id),
        )
    notify(
        db,
        business_id=family[0].id,
        category=CATEGORY_BILLING,
        type_key="pilot_access",
        severity=SEVERITY_WARNING,
        title="Your pilot access has ended",
        body="Thank you for piloting ORLA. Subscribe to keep uploading data; everything you've imported is kept.",
        action_label="Subscribe",
        action_url="/onboarding",
        visible_to_role="owner",
        dedup_key=f"pilot_access:{family[0].id}",
    )
    db.commit()


def find_owned_businesses(db: Session, *, owner_email: str) -> list[Business]:
    """Standalone (non-branch) businesses owned by this login email."""
    return list(
        db.scalars(
            select(Business)
            .join(Membership, Membership.business_id == Business.id)
            .join(User, User.id == Membership.user_id)
            .where(
                User.email.ilike(owner_email),
                Membership.role == "owner",
                Business.parent_business_id.is_(None),
                Business.deleted_at.is_(None),
            )
        ).all()
    )
