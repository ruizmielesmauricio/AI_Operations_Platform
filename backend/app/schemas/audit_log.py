import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    """GET .../audit-logs — read-only. Exposes exactly the fields already
    on AuditLog (app/models/audit_log.py); no internal secrets, nothing
    beyond what confirm_mapping/business/billing writes already store."""

    id: uuid.UUID
    action: str
    user_id: str
    target_type: str
    target_id: str
    event_metadata: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
