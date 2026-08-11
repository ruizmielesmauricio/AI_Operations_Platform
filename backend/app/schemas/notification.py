import uuid
from datetime import datetime

from pydantic import BaseModel


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
