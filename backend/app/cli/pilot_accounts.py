"""Operator tool for complimentary pilot/tester accounts — free, fully
working access with no Stripe involvement (Subscription.is_complimentary).

Run inside the backend container / any environment with DATABASE_URL set:

    python -m app.cli.pilot_accounts grant  --email owner@shop.ie
    python -m app.cli.pilot_accounts grant  --business-id <uuid>
    python -m app.cli.pilot_accounts list
    python -m app.cli.pilot_accounts revoke --email owner@shop.ie

The tester signs up normally first (so a user and a business exist); `grant`
then flips every shop they own (branches included) to complimentary-active.
Converting to a paying customer later needs no operator step: when they
subscribe through the normal Stripe Checkout, the first real Stripe event
replaces the placeholder and clears the flag. A real, paying subscription
is never overwritten by `grant`.
"""

import argparse
import sys
import uuid

from sqlalchemy.orm import Session

from app.models.base import SessionLocal
from app.models.business import Business
from app.models.membership import Membership
from app.models.subscription import Subscription
from app.models.user import User
from app.repositories.audit_log import record_audit_event
from app.repositories.subscription import SubscriptionRepository

_OPERATOR = "system:pilot_accounts"


class PilotAccountError(Exception):
    pass


def _owned_businesses(db: Session, email: str) -> list[Business]:
    user = db.query(User).filter(User.email.ilike(email.strip())).first()
    if user is None:
        raise PilotAccountError(f"No account with email {email!r} — they need to sign up first.")
    rows = (
        db.query(Business)
        .join(Membership, Membership.business_id == Business.id)
        .filter(Membership.user_id == user.id, Membership.role == "owner", Business.deleted_at.is_(None))
        .order_by(Business.created_at)
        .all()
    )
    if not rows:
        raise PilotAccountError(f"{email!r} doesn't own a business yet — they need to create one first.")
    return rows


def grant(db: Session, *, email: str | None = None, business_id: uuid.UUID | None = None) -> list[Business]:
    businesses = _owned_businesses(db, email) if email else _single_business(db, business_id)
    repo = SubscriptionRepository(db)
    granted = []
    for business in businesses:
        try:
            repo.grant_complimentary(business.id)
        except ValueError as exc:
            raise PilotAccountError(f"{business.name}: {exc}") from exc
        record_audit_event(
            db, business_id=business.id, user_id=_OPERATOR, action="complimentary_granted",
            target_type="subscription", target_id=str(business.id),
        )
        granted.append(business)
    db.commit()
    return granted


def revoke(db: Session, *, email: str | None = None, business_id: uuid.UUID | None = None) -> list[Business]:
    businesses = _owned_businesses(db, email) if email else _single_business(db, business_id)
    repo = SubscriptionRepository(db)
    revoked = []
    for business in businesses:
        if repo.revoke_complimentary(business.id) is not None:
            record_audit_event(
                db, business_id=business.id, user_id=_OPERATOR, action="complimentary_revoked",
                target_type="subscription", target_id=str(business.id),
            )
            revoked.append(business)
    db.commit()
    return revoked


def list_complimentary(db: Session) -> list[tuple[Business, Subscription]]:
    return (
        db.query(Business, Subscription)
        .join(Subscription, Subscription.business_id == Business.id)
        .filter(Subscription.is_complimentary.is_(True), Business.deleted_at.is_(None))
        .order_by(Business.created_at)
        .all()
    )


def _single_business(db: Session, business_id: uuid.UUID | None) -> list[Business]:
    business = db.get(Business, business_id) if business_id else None
    if business is None or business.deleted_at is not None:
        raise PilotAccountError(f"No such business: {business_id}")
    return [business]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pilot_accounts", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("grant", "revoke"):
        p = sub.add_parser(name)
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--email", help="the owner's login email (applies to every shop they own)")
        group.add_argument("--business-id", type=uuid.UUID)
    sub.add_parser("list")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        try:
            if args.command == "list":
                rows = list_complimentary(db)
                for business, sub_row in rows:
                    print(f"{business.id}  {business.name:<30}  status={sub_row.status}")
                print(f"{len(rows)} complimentary account(s)")
            else:
                action = grant if args.command == "grant" else revoke
                done = action(db, email=args.email, business_id=args.business_id)
                verb = "Granted complimentary access to" if args.command == "grant" else "Revoked complimentary access from"
                for business in done:
                    print(f"{verb}: {business.name} ({business.id})")
                if not done:
                    print("Nothing changed (no complimentary account matched).")
        except PilotAccountError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
