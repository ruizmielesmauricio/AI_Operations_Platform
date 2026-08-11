import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.notification import Notification

# Real limit/offset pagination (ORLA Notifications/Security/Retention
# prompt's "the endpoint never returns an unbounded notification
# history") — matches this codebase's established Transactions-drill-down
# style (app/application/transactions.py's PaginatedResult/MAX_PAGE_SIZE
# pattern) rather than inventing a second pagination shape.
_DEFAULT_LIST_LIMIT = 25
MAX_LIST_LIMIT = 100

# The customer-impacting "incident" type_keys (ORLA Notifications/
# Security/Retention prompt, section 3) — a blocking condition worth a
# visible in-app banner while it's still open, not just a Notification
# Centre entry someone has to go look at. Kept as a fixed tuple here
# (mirrored nowhere else) since it's purely a query-shape concern, not a
# notification-content one.
_SYSTEM_STATUS_TYPE_KEYS = ("report_failed", "report_delayed", "import_failed", "ai_insights_unavailable")


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

    def _filtered_query(
        self,
        business_id: uuid.UUID,
        *,
        role: str,
        category: str | None,
        status: str | None,
        severity: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ):
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
        # Half-open [start_at, end_at) — same convention as
        # app/analytics/period.py's MetricPeriod, resolved from the
        # caller's Today/7d/30d/custom selection before it ever reaches
        # here (app/application/notifications.py::resolve_notification_
        # date_range). Both None means "no date filter."
        if start_at is not None:
            query = query.where(Notification.created_at >= start_at)
        if end_at is not None:
            query = query.where(Notification.created_at < end_at)
        return query

    def list_active_incidents(self, business_id: uuid.UUID, *, role: str) -> list[Notification]:
        """Backs the in-app system-status banner (ORLA Notifications/
        Security/Retention prompt, section 3: "show a visible in-app
        status/banner while a blocking incident is active"). "Active" =
        still open (not dismissed) — read/unread doesn't matter here,
        unlike the unread badge; a customer having already seen the
        warning doesn't mean the underlying condition resolved. Ordered
        newest first, no limit — there are only ever a handful of
        possible type_keys, so this can never return an unbounded list.
        """
        query = select(Notification).where(
            Notification.business_id == business_id,
            Notification.type_key.in_(_SYSTEM_STATUS_TYPE_KEYS),
            Notification.status != "dismissed",
        )
        query = self._role_filter(query, role)
        query = query.order_by(Notification.created_at.desc())
        return list(self.session.scalars(query))

    def list_for_business(
        self,
        business_id: uuid.UUID,
        *,
        role: str,
        category: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = _DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        """Returns (page of items, total matching rows) — the total is a
        second, cheap count() query, not len(items), so pagination
        metadata is correct even on a page that isn't full (e.g. the last
        page). Deterministic ordering (created_at desc, id desc as a
        tie-breaker for same-timestamp rows) so two pages never overlap
        or skip a row."""
        query = self._filtered_query(
            business_id, role=role, category=category, status=status, severity=severity,
            start_at=start_at, end_at=end_at,
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        page = list(
            self.session.scalars(
                query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).offset(offset)
            )
        )
        return page, total

    def list_items_for_business(
        self,
        business_id: uuid.UUID,
        *,
        role: str,
        category: str | None = None,
        status: str | None = None,
        severity: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = MAX_LIST_LIMIT,
        offset: int = 0,
    ) -> list[Notification]:
        """Convenience wrapper over list_for_business for a caller that
        only wants the page of rows, not the pagination total — every
        internal (non-API) caller in this codebase today (tests, and any
        future "just give me the open notifications" use). Defaults to
        MAX_LIST_LIMIT, not the smaller page-sized default, since callers
        of this method were never expecting to need to page through
        results at all before pagination existed."""
        items, _ = self.list_for_business(
            business_id, role=role, category=category, status=status, severity=severity,
            start_at=start_at, end_at=end_at, limit=limit, offset=offset,
        )
        return items

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
