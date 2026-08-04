from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.membership import Membership


def create_business_with_owner(
    db: Session, *, name: str, template: str, timezone: str, owner_user_id: str
) -> Business:
    """Creates the business and its owner membership in one transaction —
    a business must never exist without at least one member (PR-1.1).
    """
    business = Business(name=name, template=template, timezone=timezone)
    db.add(business)
    db.flush()
    db.add(Membership(business_id=business.id, user_id=owner_user_id, role="owner"))
    db.commit()
    db.refresh(business)
    return business


def list_businesses_for_user(db: Session, *, user_id: str) -> list[tuple[Business, Membership]]:
    return (
        db.query(Business, Membership)
        .join(Membership, Membership.business_id == Business.id)
        .filter(Membership.user_id == user_id)
        .all()
    )
