import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.repositories.notification import NotificationRepository
from app.schemas.notification import (
    NotificationCategoryFilter,
    NotificationListOut,
    NotificationOut,
    NotificationSeverityFilter,
    NotificationStatusFilter,
)
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
def list_notifications(
    category: NotificationCategoryFilter | None = None,
    status_filter: NotificationStatusFilter | None = Query(default=None, alias="status"),
    severity: NotificationSeverityFilter | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> NotificationListOut:
    repo = NotificationRepository(db)
    items = repo.list_for_business(
        membership.business_id, role=membership.role, category=category, status=status_filter, severity=severity
    )
    unread_count = repo.count_unread(membership.business_id, role=membership.role)
    return NotificationListOut(
        items=[NotificationOut.model_validate(n) for n in items], unread_count=unread_count
    )


@router.get("/unread-count")
def get_unread_count(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict:
    count = NotificationRepository(db).count_unread(membership.business_id, role=membership.role)
    return {"unread_count": count}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> NotificationOut:
    repo = NotificationRepository(db)
    notification = repo.get_for_business(notification_id, membership.business_id, role=membership.role)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification = repo.mark_read(notification)
    db.commit()
    return NotificationOut.model_validate(notification)


@router.post("/mark-all-read")
def mark_all_notifications_read(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict:
    updated = NotificationRepository(db).mark_all_read(membership.business_id, role=membership.role)
    db.commit()
    return {"updated": updated}


@router.post("/{notification_id}/dismiss", response_model=NotificationOut)
def dismiss_notification(
    notification_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> NotificationOut:
    repo = NotificationRepository(db)
    notification = repo.get_for_business(notification_id, membership.business_id, role=membership.role)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification = repo.dismiss(notification)
    db.commit()
    return NotificationOut.model_validate(notification)
