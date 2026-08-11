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
    unread_count: int
