import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class EmployeeSeatCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=128)
    surname: str = Field(min_length=1, max_length=128)
    email: EmailStr
    role: str = Field(min_length=1, max_length=32)  # validated against EMPLOYEE_SEAT_ROLES in the app layer


class EmployeeSeatOut(BaseModel):
    id: uuid.UUID
    first_name: str
    surname: str
    email: str
    role: str
    status: str  # "pending_payment" | "active" | "payment_failed" | "canceled"
    created_at: datetime

    model_config = {"from_attributes": True}


class EmployeeSeatCreateResponse(BaseModel):
    employee_seat: EmployeeSeatOut
    # Where the frontend sends the owner next — Stripe Checkout, exactly
    # like Add a branch's own redirectToCheckout pattern.
    checkout_url: str
