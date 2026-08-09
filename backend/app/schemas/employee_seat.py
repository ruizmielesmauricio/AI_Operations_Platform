import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class EmployeeSeatCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=128)
    surname: str = Field(min_length=1, max_length=128)
    email: EmailStr
    role: str = Field(min_length=1, max_length=32)  # validated against EMPLOYEE_SEAT_ROLES in the app layer
    # Optional, consistent with the owner/business profile — same live
    # Geoapify-suggestion input on the frontend.
    address_line1: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=128)


class EmployeeSeatUpdate(BaseModel):
    """PATCH .../employee-seats/{id} — email and status are deliberately
    not editable here: changing email would silently break reconciliation
    matching, and status only ever changes via the payment webhook."""

    first_name: str = Field(min_length=1, max_length=128)
    surname: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=32)
    address_line1: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=128)


class EmployeeSeatOut(BaseModel):
    id: uuid.UUID
    first_name: str
    surname: str
    email: str
    role: str
    status: str  # "pending_payment" | "active" | "payment_failed" | "canceled"
    # True once a real account has been linked (either it already existed
    # at invite time, or the employee has since signed up/logged in with
    # a matching email) — distinct from `status`, which only tracks
    # payment. The frontend uses this to explain what's actually still
    # pending when status is "pending_payment": payment, signup, or both.
    account_linked: bool
    address_line1: str | None
    city: str | None
    postal_code: str | None
    country: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_seat(cls, seat) -> "EmployeeSeatOut":
        return cls(
            id=seat.id,
            first_name=seat.first_name,
            surname=seat.surname,
            email=seat.email,
            role=seat.role,
            status=seat.status,
            account_linked=seat.user_id is not None,
            address_line1=seat.address_line1,
            city=seat.city,
            postal_code=seat.postal_code,
            country=seat.country,
            created_at=seat.created_at,
        )


class EmployeeSeatCreateResponse(BaseModel):
    employee_seat: EmployeeSeatOut
    # Where the frontend sends the owner next — Stripe Checkout, exactly
    # like Add a branch's own redirectToCheckout pattern.
    checkout_url: str
