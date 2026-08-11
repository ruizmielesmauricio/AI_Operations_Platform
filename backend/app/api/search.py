from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.search import DEFAULT_LIMIT_PER_GROUP, MAX_LIMIT_PER_GROUP, global_search
from app.models.membership import Membership
from app.schemas.search import SearchResultOut
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/search", tags=["search"])


@router.get("", response_model=SearchResultOut)
def search_business(
    q: str = Query(default="", max_length=255),
    limit: int = Query(default=DEFAULT_LIMIT_PER_GROUP, ge=1, le=MAX_LIMIT_PER_GROUP),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> SearchResultOut:
    # get_current_membership is the entire tenant/branch boundary here —
    # membership.business_id (never the raw path value trusted directly)
    # is the only business global_search ever touches; a branch is just
    # another Business row with its own separate Membership requirement,
    # so this can never accidentally reach a sibling branch's data.
    return global_search(db, business_id=membership.business_id, query=q, limit=limit)
