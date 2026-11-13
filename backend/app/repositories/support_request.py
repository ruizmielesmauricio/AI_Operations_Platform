import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.support_request import SupportRequest

MAX_LIST_LIMIT = 100


class SupportRequestRepository:
    """Flush only, caller commits — same convention as every repository
    here. Every per-tenant query filters on business_id; the only
    cross-tenant reader is list_all_for_operator, used by the operator
    script, never by an HTTP route."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, **fields) -> SupportRequest:
        request = SupportRequest(status="open", **fields)
        self.session.add(request)
        self.session.flush()
        return request

    def count_created_since(self, business_id: uuid.UUID, since: datetime) -> int:
        query = select(func.count()).select_from(SupportRequest).where(
            SupportRequest.business_id == business_id, SupportRequest.created_at >= since
        )
        return self.session.scalar(query) or 0

    def find_open_duplicate(
        self, business_id: uuid.UUID, user_id: str, question: str, since: datetime
    ) -> SupportRequest | None:
        return self.session.scalar(
            select(SupportRequest).where(
                SupportRequest.business_id == business_id,
                SupportRequest.user_id == user_id,
                SupportRequest.question == question,
                SupportRequest.status == "open",
                SupportRequest.created_at >= since,
            )
        )

    def list_for_business(
        self, business_id: uuid.UUID, *, user_id: str | None = None, limit: int = 50
    ) -> list[SupportRequest]:
        query = select(SupportRequest).where(SupportRequest.business_id == business_id)
        if user_id is not None:
            query = query.where(SupportRequest.user_id == user_id)
        query = query.order_by(SupportRequest.created_at.desc(), SupportRequest.id.desc()).limit(
            min(max(limit, 1), MAX_LIST_LIMIT)
        )
        return list(self.session.scalars(query))

    def get(self, request_id: uuid.UUID) -> SupportRequest | None:
        return self.session.get(SupportRequest, request_id)

    def list_all_for_operator(self, *, status: str | None = None, limit: int = 200) -> list[SupportRequest]:
        query = select(SupportRequest)
        if status is not None:
            query = query.where(SupportRequest.status == status)
        return list(self.session.scalars(query.order_by(SupportRequest.created_at.desc()).limit(limit)))
