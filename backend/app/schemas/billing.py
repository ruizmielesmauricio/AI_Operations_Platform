import uuid

from pydantic import BaseModel, EmailStr


class CheckoutSessionRequest(BaseModel):
    # TODO(Phase 2 auth): take business_id from the verified tenant session
    # (app/security/tenant.py) once Supabase Auth is wired up, instead of
    # trusting it from the request body.
    business_id: uuid.UUID
    business_email: EmailStr


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionRequest(BaseModel):
    business_id: uuid.UUID


class PortalSessionResponse(BaseModel):
    portal_url: str
