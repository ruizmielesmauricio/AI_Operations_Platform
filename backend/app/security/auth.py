"""Auth ownership map (ORLA Notifications/Security/Retention prompt,
section 4's own "first inspect the authentication architecture and
determine which authentication methods ORLA owns versus delegates"
requirement) — recorded here since this module is the actual boundary.

ORLA owns NOTHING about authentication itself, only tenant-scoping on
top of an already-authenticated identity (see app/security/tenant.py):

- Sign-up, sign-in (email/password AND Google OAuth), password reset
  (frontend/app/forgot-password, /reset-password, /login), session
  issuance/refresh, and token verification (the JWKS check right below)
  are all 100% Supabase Auth (ADR-013: "Supabase's database/storage
  products are never used" — Auth is the one exception, used in full).
  No password hash, reset token, or session table exists anywhere in
  this backend's own schema — decode_supabase_jwt below is the entire
  extent of this backend's involvement: verify a token Supabase already
  issued, never issue or store one itself.
- The password-reset flow's every literal requirement in this prompt
  (generic non-enumerating response, a cryptographically secure single-
  use token stored only as a hash, 15-30 minute expiry, rate limiting by
  account/IP, session invalidation semantics on the provider side) is
  therefore already satisfied by Supabase's own implementation, not
  something to rebuild in parallel — a second, homemade token system
  alongside Supabase's own would be redundant risk, not extra safety.

What's genuinely NOT built, and why, disclosed here rather than silently
skipped:
- Explicit "revoke every other active session after a successful
  password reset" needs Supabase's Admin API, which needs a
  SUPABASE_SERVICE_ROLE_KEY — no such setting exists anywhere in
  app/settings/config.py or this deployment's environment today. Not
  something this backend can fabricate; needs the account owner to
  provision that secret first.
- A server-side audit-log entry or notification on "password changed" /
  "email changed" needs Supabase Auth Hooks (a webhook, configured in
  the Supabase project dashboard, outside this codebase and outside API
  access) POSTing to a new receiver route here — the receiver is real,
  buildable code, but activating it needs a dashboard setting only the
  account owner can make, the same category of gap as the Stripe
  webhook secret already disclosed elsewhere in this project's history.
- Repeated-failed-sign-in/lockout and new-device/new-location sign-in
  are both explicitly conditional in this prompt ("if reliable data
  already exists" / "if it can be implemented reliably") — no failed-
  attempt log or session/device/IP history exists anywhere in this
  stateless-JWT backend, so neither precondition holds; correctly not
  built, per the prompt's own instruction, rather than guessed at.
- MFA enable/disable/recovery: conditional on "if MFA exists" — no MFA
  flow exists anywhere in frontend/app/login or Supabase's configured
  providers for this project, so there is nothing to notify about.
- "Owner/administrator account changed": no ownership-transfer feature
  exists anywhere in this codebase (a business's owner is fixed at
  creation, via its first Membership row) — nothing to notify about.
"""

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClientError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.user import User
from app.settings.config import get_settings

settings = get_settings()

# auto_error=False so a missing header raises our own 401 with a clear
# message, instead of FastAPI's generic one.
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedUser:
    id: str
    email: str


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    # Supabase signs Auth tokens with the project's asymmetric key (ES256),
    # not a shared HMAC secret — verifying them needs the project's public
    # key, published at this well-known JWKS URL. PyJWKClient fetches and
    # caches it (cache_keys=True) so this is a one-off cost per process, not
    # a network call on every request. Overridden in tests (see
    # tests/auth_helpers.py) to avoid a real network dependency there.
    return jwt.PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def decode_supabase_jwt(token: str) -> dict:
    """Verifies a Supabase Auth access token against the project's published
    JWKS (ES256) — see _jwks_client above for why this isn't a shared secret.
    """
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except (jwt.InvalidTokenError, PyJWKClientError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session"
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """Verifies the bearer token only — no database access. Use this for
    anything that just needs to know who's asking, without needing a
    local User row to exist yet.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    claims = decode_supabase_jwt(credentials.credentials)
    return AuthenticatedUser(id=claims["sub"], email=claims.get("email", ""))


def get_current_user_synced(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    """Same as get_current_user, but also ensures a local `users` row
    exists (upsert), since Supabase is the identity source of truth but
    memberships/audit_logs/etc. need a local foreign key to point at.
    Use this dependency on any route that writes data tied to a user_id.

    Also the one place a newly (or re-)authenticated user gets checked
    against any pending employee-seat invites addressed to their email
    (app/application/employee_seats.py::reconcile_pending_employee_seats)
    — this is what lets an owner add someone by email before they've
    ever signed up, and have access apply automatically the moment they
    do, with no separate "accept invite" step.
    """
    # Normalized to lowercase on write, not just compared case-
    # insensitively on read — closes the real bug this stored a raw-case
    # value causing (an owner adding someone who'd genuinely already
    # signed up got "No account found" purely from a casing mismatch)
    # at the source, not just at every call site that happens to guard
    # against it.
    normalized_email = current_user.email.lower()
    user = db.get(User, current_user.id)
    if user is None:
        user = User(id=current_user.id, email=normalized_email)
        db.add(user)
        db.flush()
    elif user.email != normalized_email:
        user.email = normalized_email
        db.flush()

    # Local import: app/application/employee_seats.py doesn't import
    # anything from app/security/, so this isn't breaking a cycle — kept
    # local anyway to keep this low-level auth module's own import list
    # free of application-layer concerns at module load time.
    from app.application.employee_seats import reconcile_pending_employee_seats

    reconcile_pending_employee_seats(db, user)
    db.commit()
    return current_user
