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
    """
    user = db.get(User, current_user.id)
    if user is None:
        db.add(User(id=current_user.id, email=current_user.email))
        db.commit()
    elif user.email != current_user.email:
        user.email = current_user.email
        db.commit()
    return current_user
