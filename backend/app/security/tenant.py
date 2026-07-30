import uuid

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.security.auth import AuthenticatedUser, get_current_user


def get_current_membership(
    business_id: uuid.UUID = Path(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Membership:
    """The tenant-isolation gate (PR-6.1, PR-6.2).

    business_id in the URL is never trusted on its own — this function
    verifies a membership row actually exists for (business_id,
    current_user) before returning it. No membership, no access,
    regardless of what the client puts in the URL. Every tenant-scoped
    route must depend on this (directly or via a dependency that itself
    depends on it), never read business_id from the path and query
    straight to a repository.
    """
    membership = (
        db.query(Membership)
        .filter(Membership.business_id == business_id, Membership.user_id == current_user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this business")
    return membership
