from sqlalchemy import DECIMAL, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class AIRequest(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Usage/cost log for every AI Provider Gateway call — one row per
    request, regardless of which conversational-agent lane it served
    (PR-5.5, NFR-6). The gateway is the only writer of this table.
    """

    __tablename__ = "ai_requests"

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lane: Mapped[str] = mapped_column(String(32), nullable=False)  # business_qa | report_explain | support
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_eur: Mapped[object] = mapped_column(DECIMAL(10, 6), nullable=False, default=0)
    success: Mapped[bool] = mapped_column(nullable=False, default=True)
