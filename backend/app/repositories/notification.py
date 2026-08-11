import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.notification import Notification

# Bounded list, matching this codebase's one other list route
# (AuditLogRepository) rather than a full pagination framework — a
# notification centre at this app's current scale never has thousands of
# open rows, and dismissed/read history isn't meant to be an infinite
# archive.
_DEFAULT_LIST_LIMIT = 100


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _role_filter(query, role: str):
        # Owner sees every notification; any other role never sees a row
        # marked owner-only (billing/branch subscription status today) —
        # enforced here, not trusted from the client, so a manager/staff
        # request can never see it by passing a different filter.
        if role == "owner":
            return query
        return query.where(Notification.visible_to_role.is_(None))

    def list_for_business(
        self,
        business_id: uuid.UUID,
        *,
        role: str,
        category: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = _DEFAULT_LIST_LIMIT,
    ) -> list[Notification]:
        query = select(Notification).where(Notification.business_id == business_id)
        query = self._role_filter(query, role)
        if category is not None:
            query = query.where(Notification.category == category)
        if severity is not None:
            query = query.where(Notification.severity == severity)
        if status is not None:
            query = query.where(Notification.status == status)
        else:
            # Default view excludes dismissed — matches every other
            # "active list" convention in this codebase (Alert's own
            # list_active_for_business hides resolved rows by default).
            query = query.where(Notification.status != "dismissed")
        query = query.order_by(Notification.created_at.desc()).limit(limit)
        return list(self.session.scalars(query))

    def count_unread(self, business_id: uuid.UUID, *, role: str) -> int:
        query = select(func.count()).select_from(Notification).where(
            Notification.business_id == business_id, Notification.status == "unread"
        )
        query = self._role_filter(query, role)
        return self.session.scalar(query) or 0

    def get_for_business(self, notification_id: uuid.UUID, business_id: uuid.UUID, *, role: str) -> Notification | None:
        query = select(Notification).where(
            Notification.id == notification_id, Notification.business_id == business_id
        )
        query = self._role_filter(query, role)
        return self.session.scalar(query)

    def get_open_by_dedup_key(self, business_id: uuid.UUID, dedup_key: str) -> Notification | None:
        return self.session.scalar(
            select(Notification).where(
                Notification.business_id == business_id,
                Notification.dedup_key == dedup_key,
                Notification.status != "dismissed",
            )
        )

    def create(
        self,
        *,
        business_id: uuid.UUID,
        category: str,
        type_key: str,
        severity: str,
        title: str,
        body: str,
        action_label: str | None = None,
        action_url: str | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        visible_to_role: str | None = None,
        dedup_key: str | None = None,
    ) -> Notification:
        notification = Notification(
            business_id=business_id,
            category=category,
            type_key=type_key,
            severity=severity,
            title=title,
            body=body,
            action_label=action_label,
            action_url=action_url,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            visible_to_role=visible_to_role,
            dedup_key=dedup_key,
            status="unread",
        )
        self.session.add(notification)
        self.session.flush()
        return notification

    def update_and_reopen(
        self, notification: Notification, *, type_key: str, severity: str, title: str, body: str
    ) -> Notification:
        """Re-triggering the same deterministic condition (e.g. the
        low-stock count changed on a later import) updates the existing
        open row in place rather than creating a duplicate — the ORLA
        Notification Centre prompt's own grouping/spam-control
        requirement. A previously-read row surfaces as unread again, since
        the underlying situation has genuinely changed; a dismissed row is
        never reached here (get_open_by_dedup_key excludes it). type_key
        is updatable too — a freshness notification can escalate from
        "no_new_data_detected" to "data_outdated" under the same dedup_key
        as more days pass, which is a change in classification, not just
        wording."""
        notification.type_key = type_key
        notification.severity = severity
        notification.title = title
        notification.body = body
        notification.status = "unread"
        notification.read_at = None
        self.session.flush()
        return notification

    def mark_read(self, notification: Notification) -> Notification:
        if notification.status == "unread":
            notification.status = "read"
            notification.read_at = datetime.now(timezone.utc)
            self.session.flush()
        return notification

    def mark_all_read(self, business_id: uuid.UUID, *, role: str) -> int:
        query = select(Notification).where(
            Notification.business_id == business_id, Notification.status == "unread"
        )
        query = self._role_filter(query, role)
        rows = list(self.session.scalars(query))
        now = datetime.now(timezone.utc)
        for row in rows:
            row.status = "read"
            row.read_at = now
        self.session.flush()
        return len(rows)

    def dismiss(self, notification: Notification) -> Notification:
        notification.status = "dismissed"
        self.session.flush()
        return notification
