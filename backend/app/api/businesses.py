import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.business import Business
from app.models.membership import Membership
from app.repositories.business import create_business_with_owner, list_businesses_for_user
from app.schemas.business import BusinessCreate, BusinessOut
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses", tags=["businesses"])


@router.post("", response_model=BusinessOut, status_code=status.HTTP_201_CREATED)
def create_business(
    payload: BusinessCreate,
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> BusinessOut:
    business = create_business_with_owner(
        db,
        name=payload.name,
        template=payload.template,
        timezone=payload.timezone,
        owner_user_id=current_user.id,
    )
    return BusinessOut(
        id=business.id,
        name=business.name,
        template=business.template,
        timezone=business.timezone,
        role="owner",
    )


@router.get("", response_model=list[BusinessOut])
def list_my_businesses(
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> list[BusinessOut]:
    rows = list_businesses_for_user(db, user_id=current_user.id)
    return [
        BusinessOut(
            id=business.id,
            name=business.name,
            template=business.template,
            timezone=business.timezone,
            role=membership.role,
        )
        for business, membership in rows
    ]


@router.get("/{business_id}", response_model=BusinessOut)
def get_business(
    business_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BusinessOut:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return BusinessOut(
        id=business.id,
        name=business.name,
        template=business.template,
        timezone=business.timezone,
        role=membership.role,
    )
