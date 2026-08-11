import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Must stay in sync with the CATEGORY_*/SEVERITY_* constants in
# app/application/notifications.py (the only place that ever creates a
# Notification) and with frontend/types/index.ts's NotificationCategory/
# NotificationSeverity — typed here so an invalid ?category=/?severity=/
# ?status= filter value 422s automatically (FastAPI validates a Literal
# query param before the route body ever runs) instead of silently
# matching zero rows.
NotificationCategoryFilter = Literal[
    "stock", "data_uploads", "reports", "orla_insights", "team", "billing", "branches", "security_account"
]
NotificationSeverityFilter = Literal["info", "success", "warning", "critical"]
NotificationStatusFilter = Literal["unread", "read", "dismissed"]
# Must stay in sync with app/application/notifications.py's own
# NOTIFICATION_DATE_FILTERS tuple.
NotificationDateFilterOption = Literal["today", "7d", "30d", "custom"]


class NotificationOut(BaseModel):
    id: uuid.UUID
    category: str
    type_key: str
    severity: str
    title: str
    body: str
    action_label: str | None
    action_url: str | None
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    status: str
    created_at: datetime
    read_at: datetime | None

    model_config = {"from_attributes": True}


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    limit: int
    offset: int
    # Always the caller's role-scoped total unread count across every
    # category/severity/date — deliberately *not* re-filtered by this
    # same request's category/severity/date_filter params, so switching
    # to "Today" never makes a real backlog of unread notifications from
    # other days look like it silently disappeared. Matches the dedicated
    # GET .../unread-count route's own always-unfiltered behaviour
    # (app/api/notifications.py), which AppNav's badge polls independently.
    unread_count: int


class SystemStatusOut(BaseModel):
    has_active_incident: bool
    # Small (a handful of possible type_keys at most) — the banner shows
    # the most recent one; the rest stay available in the Notification
    # Centre as always.
    incidents: list[NotificationOut]
