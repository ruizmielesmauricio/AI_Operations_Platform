import uuid
from datetime import datetime

from pydantic import BaseModel


class AlertOut(BaseModel):
    id: uuid.UUID
    alert_type: str
    product_id: uuid.UUID | None
    payload: dict
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
