from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.user import User
from app.security.auth import AuthenticatedUser, get_current_user_synced

router = APIRouter(prefix="/account/security", tags=["account-security"])


@router.post("/revoke-other-sessions", status_code=status.HTTP_200_OK)
def revoke_other_sessions_after_password_reset(
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Immediately deny ORLA API access to this user's other sessions.

    Supabase's client-side `signOut({scope: "others"})` revokes refresh
    tokens, but access JWTs can remain valid until expiry. This endpoint is
    intentionally user-scoped: it never accepts a user id, trusts only the
    verified recovery session, and retains that session as the sole exception.
    """
    if not current_user.session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This session cannot be used to revoke other sessions. Request a new password reset link.",
        )
    user = db.get(User, current_user.id)
    if user is None:  # get_current_user_synced creates it; defensive only.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account record not found")
    user.session_revoked_after = datetime.now(timezone.utc)
    user.session_exception_id = current_user.session_id
    db.commit()
    return {"revoked": True}
