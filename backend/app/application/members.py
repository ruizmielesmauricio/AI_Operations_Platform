"""Read-only aggregation of who's attached to a business — the owner
(from Business.manager_first_name/surname + their Membership) plus every
employee seat — into one unified display list, e.g. "Mauricio Ruiz -
Owner" / "Antonio Ruiz - Manager". No calculation logic of its own,
purely a merge of two existing sources (app/application/employee_seats.py
owns the employee-seat lifecycle itself; this module only reads).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.membership import Membership
from app.repositories.employee_seat import EmployeeSeatRepository


@dataclass
class Member:
    # The owner's own real user id; an employee's linked user id, or
    # None if they haven't signed up/logged in yet.
    user_id: str | None
    # None for the owner's row — they have no EmployeeSeat, just their
    # Membership and the Business's own profile fields.
    employee_seat_id: uuid.UUID | None
    first_name: str
    surname: str
    role: str  # "owner" | "manager" | "staff"
    status: str  # "active" (owner, always) | EmployeeSeat.status for everyone else
    account_linked: bool  # True for the owner, always


def list_business_members(db: Session, business_id: uuid.UUID) -> list[Member]:
    members: list[Member] = []
    business = db.get(Business, business_id)
    # Exactly one owner Membership per business by construction — every
    # creation path (create_business_with_owner, create_branch_business)
    # creates exactly one, and no route ever adds a second.
    owner_membership = (
        db.query(Membership).filter(Membership.business_id == business_id, Membership.role == "owner").first()
    )
    if business is not None and owner_membership is not None:
        members.append(
            Member(
                user_id=owner_membership.user_id,
                employee_seat_id=None,
                first_name=business.manager_first_name or "",
                surname=business.manager_surname or "",
                role="owner",
                status="active",
                account_linked=True,
            )
        )
    for seat in EmployeeSeatRepository(db).list_for_business(business_id):
        members.append(
            Member(
                user_id=seat.user_id,
                employee_seat_id=seat.id,
                first_name=seat.first_name,
                surname=seat.surname,
                role=seat.role,
                status=seat.status,
                account_linked=seat.user_id is not None,
            )
        )
    return members
