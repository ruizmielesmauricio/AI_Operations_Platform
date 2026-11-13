"""The human support handoff (PR-5.7): "Contact support" records the
question so the ORLA team can follow up.

One call, one transaction: the SupportRequest row, an audit event and an
owner-visible notification land in the same commit (flush-only helpers,
the API route commits). Email to the ORLA team is optional and happens
after the commit — see _email_operator.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.application.notifications import notify_support_request_created
from app.email.service import send_support_request_email
from app.models.business import Business
from app.models.support_request import SupportRequest
from app.repositories.audit_log import record_audit_event
from app.repositories.support_request import SupportRequestRepository
from app.settings.config import get_settings
from app.support.knowledge_base import get_knowledge_base

logger = logging.getLogger(__name__)

SOURCES = ("chat", "help_page")
# Bounded so a stuck button or a script can't flood the team or the
# owner's Notification Centre.
MAX_REQUESTS_PER_BUSINESS_PER_DAY = 10
# The same person sending the same question again while it's still open is
# treated as a double-click, not a new request.
_DUPLICATE_WINDOW = timedelta(hours=24)


class SupportRequestRateLimited(Exception):
    """More than MAX_REQUESTS_PER_BUSINESS_PER_DAY in the last 24 hours."""


class InvalidSupportRequest(ValueError):
    """Empty question or an unknown source."""


def _clean_question(question: str) -> str:
    return " ".join(question.split())


def create_support_request(
    db: Session,
    *,
    business_id: uuid.UUID,
    user_id: str,
    requester_email: str,
    requester_role: str,
    question: str,
    source: str,
    orla_answer: str | None = None,
    article_slugs: list[str] | None = None,
    now: datetime | None = None,
) -> tuple[SupportRequest, bool]:
    """Returns (request, created). created=False means an identical open
    request from the same person already existed and was returned instead
    (idempotent re-submit). Raises SupportRequestRateLimited or
    InvalidSupportRequest. Never commits."""
    now = now or datetime.now(timezone.utc)
    cleaned = _clean_question(question)
    if not cleaned:
        raise InvalidSupportRequest("question is empty")
    if source not in SOURCES:
        raise InvalidSupportRequest(f"unknown source {source!r}")

    repo = SupportRequestRepository(db)
    existing = repo.find_open_duplicate(business_id, user_id, cleaned, now - _DUPLICATE_WINDOW)
    if existing is not None:
        return existing, False
    if repo.count_created_since(business_id, now - timedelta(days=1)) >= MAX_REQUESTS_PER_BUSINESS_PER_DAY:
        raise SupportRequestRateLimited()

    # Only slugs that are real help articles are kept — this list comes
    # from the browser, so it is never trusted as-is.
    kb = get_knowledge_base()
    known_slugs = [s for s in dict.fromkeys(article_slugs or []) if kb.get(s) is not None][:5]

    request = repo.create(
        business_id=business_id,
        user_id=user_id,
        requester_email=requester_email,
        question=cleaned,
        source=source,
        orla_answer=(orla_answer or None),
        article_slugs=known_slugs or None,
        # Same clock as the duplicate/rate-limit windows above — the column
        # default is the wall clock, which made those windows disagree with
        # `now` (test_rate_limited_per_business_per_day failed for a day
        # after its fixed date).
        created_at=now,
    )
    # No question text in the audit trail: it is customer free text and the
    # audit log is a security record, not a content store.
    record_audit_event(
        db,
        business_id=business_id,
        user_id=user_id,
        action="support_request_created",
        target_type="support_request",
        target_id=str(request.id),
        metadata={"source": source, "article_slugs": known_slugs, "requester_role": requester_role},
    )
    notify_support_request_created(
        db,
        business_id=business_id,
        request_id=request.id,
        requester_label="You" if requester_role == "owner" else f"A team member ({requester_email})",
        question=cleaned,
    )
    return request, True


def email_operator(db: Session, request: SupportRequest) -> bool:
    """Emails the ORLA team about a new request when a support inbox and
    the email provider are configured; otherwise does nothing (the request
    is already safely recorded and visible to the operator script). Call
    after the request's transaction has committed. Never raises."""
    settings = get_settings()
    if not settings.support_inbox_email:
        return False
    try:
        business = db.get(Business, request.business_id)
        sent = send_support_request_email(
            to_email=settings.support_inbox_email,
            business_name=business.name if business is not None else str(request.business_id),
            requester_email=request.requester_email,
            question=request.question,
            request_id=str(request.id),
        )
        if sent:
            request.operator_notified_at = datetime.now(timezone.utc)
            db.commit()
        return sent
    except Exception:  # pragma: no cover - defensive: the request itself must never be lost
        logger.exception("Failed to email the operator about support request %s", request.id)
        db.rollback()
        return False


def list_support_requests(
    db: Session, *, business_id: uuid.UUID, user_id: str, role: str, limit: int = 50
) -> list[SupportRequest]:
    """Owners see every request from their business; managers and staff
    see only their own."""
    repo = SupportRequestRepository(db)
    return repo.list_for_business(business_id, user_id=None if role == "owner" else user_id, limit=limit)


def resolve_support_request(
    db: Session, *, request_id: uuid.UUID, note: str | None, now: datetime | None = None
) -> SupportRequest | None:
    """Operator-only (scripts/support_requests.py). Never commits."""
    request = SupportRequestRepository(db).get(request_id)
    if request is None:
        return None
    request.status = "resolved"
    request.resolved_at = now or datetime.now(timezone.utc)
    request.resolution_note = note
    record_audit_event(
        db,
        business_id=request.business_id,
        user_id="operator",
        action="support_request_resolved",
        target_type="support_request",
        target_id=str(request.id),
    )
    db.flush()
    return request
