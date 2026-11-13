"""Grant, end or list free pilot access (operator-only — no HTTP route).

Run inside the backend container:

    python scripts/pilot_access.py grant --email owner@shop.ie --days 90
    python scripts/pilot_access.py grant --business-id <uuid> --days 90
    python scripts/pilot_access.py end --email owner@shop.ie
    python scripts/pilot_access.py list

A grant covers the business and all its branches; branches and staff seats
added during the pilot are free. See app/application/pilot_access.py.
"""

import argparse
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.application.pilot_access import (
    PilotAccessError,
    end_pilot_access,
    find_owned_businesses,
    grant_pilot_access,
)
from app.models.base import SessionLocal
from app.models.business import Business


def _target_ids(db, args) -> list[uuid.UUID]:
    if args.business_id:
        return [uuid.UUID(args.business_id)]
    businesses = find_owned_businesses(db, owner_email=args.email)
    if not businesses:
        sys.exit(f"No business owned by {args.email} (the owner must have signed in at least once).")
    return [b.id for b in businesses]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("grant", "end"):
        p = sub.add_parser(name)
        who = p.add_mutually_exclusive_group(required=True)
        who.add_argument("--email", help="owner's login email")
        who.add_argument("--business-id", help="business UUID")
        if name == "grant":
            p.add_argument("--days", type=int, default=90)
    sub.add_parser("list")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.command == "list":
            now = datetime.now(timezone.utc)
            rows = db.scalars(select(Business).where(Business.pilot_access_until.is_not(None))).all()
            for b in rows:
                state = "active" if b.pilot_access_until > now else "expired"
                print(f"{b.id}  {b.name:<40}  until {b.pilot_access_until:%Y-%m-%d}  {state}")
            print(f"{len(rows)} pilot business(es)")
            return
        try:
            for business_id in _target_ids(db, args):
                if args.command == "grant":
                    until = grant_pilot_access(db, business_id=business_id, days=args.days)
                    print(f"Pilot access granted to {business_id} (and its branches) until {until:%Y-%m-%d}")
                else:
                    end_pilot_access(db, business_id=business_id)
                    print(f"Pilot access ended for {business_id} (and its branches)")
        except PilotAccessError as exc:
            sys.exit(str(exc))


if __name__ == "__main__":
    main()
