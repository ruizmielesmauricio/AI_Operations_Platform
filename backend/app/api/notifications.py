import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.notifications import InvalidNotificationDateFilter, resolve_notification_date_range
from app.models.business import Business
from app.models.membership import Membership
from app.repositories.notification import MAX_LIST_LIMIT, NotificationRepository
from app.schemas.notification import (
    NotificationCategoryFilter,
    NotificationDateFilterOption,
    NotificationListOut,
    NotificationOut,
    NotificationSeverityFilter,
    NotificationStatusFilter,
    SystemStatusOut,
)
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
def list_notifications(
    category: NotificationCategoryFilter | None = None,
    status_filter: NotificationStatusFilter | None = Query(default=None, alias="status"),
    severity: NotificationSeverityFilter | None = None,
    date_filter: NotificationDateFilterOption | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=25, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> NotificationListOut:
    business = db.get(Business, membership.business_id)
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    try:
        date_range = resolve_notification_date_range(
            business.timezone, date_filter=date_filter, start_date=start_date, end_date=end_date,
            now=datetime.now(timezone.utc),
        )
    except InvalidNotificationDateFilter as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    start_at, end_at = date_range if date_range is not None else (None, None)

    repo = NotificationRepository(db)
    items, total = repo.list_for_business(
        membership.business_id, role=membership.role, category=category, status=status_filter, severity=severity,
        start_at=start_at, end_at=end_at, limit=limit, offset=offset,
    )
    unread_count = repo.count_unread(membership.business_id, role=membership.role)
    return NotificationListOut(
        items=[NotificationOut.model_validate(n) for n in items], total=total, limit=limit, offset=offset,
        unread_count=unread_count,
    )


@router.get("/unread-count")
def get_unread_count(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> dict:
    count = NotificationRepository(db).count_unread(membership.business_id, role=membership.role)
    return {"unread_count": count}


@router.get("/system-status", response_model=SystemStatusOut)
def get_system_status(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> SystemStatusOut:
    """Backs AppNav's in-app incident banner (ORLA Notifications/
    Security/Retention prompt, section 3) — polled the same way as the
    unread-count badge, independent of whatever the Notification Centre
    page itself is currently showing."""
    incidents = NotificationRepository(db).list_active_incidents(membership.business_id, role=membership.role)
    return SystemStatusOut(
        has_active_incident=len(incidents) > 0, incidents=[NotificationOut.model_validate(n) for n in incidents]
    )


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
