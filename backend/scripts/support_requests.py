"""List and resolve "Contact support" requests (operator-only — there is
deliberately no cross-tenant HTTP route).

Run inside the backend container:

    python scripts/support_requests.py list                 # open requests
    python scripts/support_requests.py list --all           # open and resolved
    python scripts/support_requests.py show <request-id>
    python scripts/support_requests.py resolve <request-id> --note "Replied by email 13/11"

Reply to the customer at the requester email shown, then resolve the
request. See app/support/service.py and ADR-028.
"""

import argparse
import sys
import uuid

from app.models.base import SessionLocal
from app.models.business import Business
from app.repositories.support_request import SupportRequestRepository
from app.support.service import resolve_support_request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--all", action="store_true", help="include resolved requests")
    show_parser = sub.add_parser("show")
    show_parser.add_argument("request_id")
    resolve_parser = sub.add_parser("resolve")
    resolve_parser.add_argument("request_id")
    resolve_parser.add_argument("--note", default=None)
    args = parser.parse_args()

    with SessionLocal() as db:
        repo = SupportRequestRepository(db)
        if args.command == "list":
            rows = repo.list_all_for_operator(status=None if args.all else "open")
            for r in rows:
                business = db.get(Business, r.business_id)
                name = business.name if business else r.business_id
                question = r.question if len(r.question) <= 70 else r.question[:69] + "…"
                print(f"{r.id}  {r.created_at:%d/%m/%Y %H:%M}  {r.status:<8}  {name}  <{r.requester_email}>  {question}")
            print(f"{len(rows)} request(s)")
            return

        request_id = uuid.UUID(args.request_id)
        if args.command == "show":
            r = repo.get(request_id)
            if r is None:
                sys.exit("No such request.")
            business = db.get(Business, r.business_id)
            print(f"Business:  {business.name if business else r.business_id}")
            print(f"From:      {r.requester_email} (user {r.user_id}) via {r.source}")
            print(f"Created:   {r.created_at:%d/%m/%Y %H:%M} UTC   Status: {r.status}")
            print(f"Articles:  {', '.join(r.article_slugs or []) or '-'}")
            print(f"\nQuestion:\n{r.question}")
            if r.orla_answer:
                print(f"\nORLA replied:\n{r.orla_answer}")
            if r.resolution_note:
                print(f"\nResolution note: {r.resolution_note}")
            return

        if resolve_support_request(db, request_id=request_id, note=args.note) is None:
            sys.exit("No such request.")
        db.commit()
        print("Resolved.")


if __name__ == "__main__":
    main()
