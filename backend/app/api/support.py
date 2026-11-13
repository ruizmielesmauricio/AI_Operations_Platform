from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.schemas.support import SupportRequestCreate, SupportRequestOut
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership
from app.support.service import (
    InvalidSupportRequest,
    SupportRequestRateLimited,
    create_support_request,
    email_operator,
    list_support_requests,
)

router = APIRouter(prefix="/businesses/{business_id}/support", tags=["support"])


@router.post("/requests", response_model=SupportRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    body: SupportRequestCreate,
    response: Response,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> SupportRequestOut:
    """"Contact support" (PR-5.7). Any member of the business may send a
    question; the business comes from the verified membership, never the
    body. Re-sending the same open question returns the existing request
    with 200 instead of creating a duplicate."""
    try:
        request, created = create_support_request(
            db,
            business_id=membership.business_id,
            user_id=membership.user_id,
            requester_email=current_user.email,
            requester_role=membership.role,
            question=body.question,
            source=body.source,
            orla_answer=body.orla_answer,
            article_slugs=body.article_slugs,
        )
    except SupportRequestRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many support requests from this business today — please try again tomorrow.",
        ) from exc
    except InvalidSupportRequest as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Please type your question.") from exc
    db.commit()
    if created:
        email_operator(db, request)
    else:
        response.status_code = status.HTTP_200_OK
    return SupportRequestOut.model_validate(request)


@router.get("/requests", response_model=list[SupportRequestOut])
def list_requests(
    limit: int = Query(default=50, ge=1, le=100),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[SupportRequestOut]:
    requests = list_support_requests(
        db, business_id=membership.business_id, user_id=membership.user_id, role=membership.role, limit=limit
    )
    return [SupportRequestOut.model_validate(r) for r in requests]
