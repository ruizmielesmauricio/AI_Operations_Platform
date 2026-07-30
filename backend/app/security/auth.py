from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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


def decode_supabase_jwt(token: str) -> dict:
    """Verifies a Supabase Auth access token.

    Supabase issues standard JWTs signed with the project's JWT secret
    (HS256). Verifying them is plain JWT decoding — no Supabase SDK or
    network call involved — which is what keeps auth decoupled from the
    database provider (ADR-013): this function only needs the shared
    secret, never a live connection to Supabase itself.
    """
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.InvalidTokenError as exc:
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
