from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class SupportRequest(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """A question a customer sent to ORLA's human support team ("Contact
    support", PR-5.7) — usually because the help knowledge base couldn't
    answer it in Ask ORLA. Tenant-scoped like every business table; the
    operator reads them across tenants only via scripts/support_requests.py
    (no cross-tenant HTTP route exists).

    Holds no business data — only the question the person chose to send and
    the minimum needed to reply to them (data minimisation): who asked and
    their login email at the time.
    """

    __tablename__ = "support_requests"

    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Snapshot of the requester's login email, so the operator can reply
    # even if the account later changes its email.
    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # chat (from Ask ORLA's handoff button) | help_page (Help page form)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    # What ORLA replied before the handoff, when it came from the chat —
    # gives the operator context without re-asking.
    orla_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Help article slugs that were shown alongside that reply.
    article_slugs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | resolved
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set once the operator has been emailed about this request. Stays NULL
    # while no support inbox / email provider is configured — a later sender
    # (or the operator script) can pick up every row where it is NULL, so
    # turning email on later needs no backfill (see app/support/service.py).
    operator_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
