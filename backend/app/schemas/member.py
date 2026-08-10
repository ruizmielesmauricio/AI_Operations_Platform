import uuid

from pydantic import BaseModel


class MemberOut(BaseModel):
    """GET /businesses/{id}/members — a unified, display-only list of
    who's attached to a business (the owner + every employee seat).
    Visible to any member (get_current_membership, not owner-gated) —
    just names and roles, none of the more sensitive employee-seat
    detail (email, Stripe ids) the owner-only .../employee-seats route
    returns for actual management.
    """

    user_id: str | None
    employee_seat_id: uuid.UUID | None
    first_name: str
    surname: str
    role: str
    status: str
    account_linked: bool

    model_config = {"from_attributes": True}
