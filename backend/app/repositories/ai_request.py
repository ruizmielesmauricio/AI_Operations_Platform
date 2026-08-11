import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_request import AIRequest


class AIRequestRepository:
    """The only writer of `ai_requests` (PR-5.5's usage log). Every real
    AI provider call — successful or not — gets exactly one row here,
    written by app/ai/service.py.
    """

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        user_id: str,
        lane: str,
        provider: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_eur: Decimal = Decimal("0"),
        success: bool = True,
    ) -> AIRequest:
        request = AIRequest(
            business_id=business_id,
            user_id=user_id,
            lane=lane,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_eur=cost_eur,
            success=success,
        )
        self.session.add(request)
        self.session.commit()
        return request

    def recent_platform_wide_success_flags(self, *, since: datetime, limit: int = 10) -> list[bool]:
        """Ops signal for the "ORLA insights temporarily unavailable"
        system-status check (app/scheduler/tick.py) — the most recent AI
        provider calls across *every* business, newest first, capped
        small since this only needs to answer "is the provider itself
        currently down," not analyse usage. Deliberately platform-wide,
        not scoped to one business: a single business's failed call could
        be many things (their own malformed question, that business's
        own rate limit); a run of failures across every business in a
        row is the actual shape a real provider outage takes.
        """
        rows = self.session.execute(
            select(AIRequest.success).where(AIRequest.created_at >= since).order_by(AIRequest.created_at.desc()).limit(limit)
        ).scalars().all()
        return list(rows)

    def count_today_for_business(self, business_id: uuid.UUID, *, now: datetime) -> int:
        """PR-5.5's usage-cap check — a rolling 24-hour window ending
        "now" (not a calendar-day boundary, which would let a business
        burst to 2x the daily cap right around local midnight). Counts
        every attempt, successful or not — a failed call still cost a
        request slot against the provider, even if it didn't cost tokens.
        """
        window_start = now - timedelta(days=1)
        return self.session.scalar(
            select(func.count()).select_from(AIRequest).where(
                AIRequest.business_id == business_id,
                AIRequest.created_at >= window_start,
            )
        ) or 0
