"""Centralized audit-log writer (PR-6.5). Every privileged/sensitive
action writes through `record_audit_event` below — never `AuditLog(...)`
constructed ad hoc in a route handler — so every entry has the same
shape and there's exactly one place to check for what does and doesn't
get logged.

Never pass in `metadata`: passwords, access/refresh tokens, API keys,
Stripe secrets, raw payment details, or more personal/customer data than
the action itself already concerns. Prefer field *names* over field
*values* when recording what changed.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

# Smallest bounded implementation, not a generic pagination framework —
# no other list route in this codebase paginates yet either. Newest-first
# is what an audit trail is read for.
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 200


class AuditLogRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_business(self, business_id: uuid.UUID, *, limit: int = _DEFAULT_LIST_LIMIT) -> list[AuditLog]:
        limit = min(max(limit, 1), _MAX_LIST_LIMIT)
        return list(
            self.session.scalars(
                select(AuditLog)
                .where(AuditLog.business_id == business_id)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
        )

    def create(
        self,
        *,
        business_id: uuid.UUID,
        user_id: str,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict | None = None,
    ) -> AuditLog:
        # Flush only, no commit — same convention as every other
        # repository in this codebase (e.g. AlertRepository). The
        # caller's own route/service owns the transaction, so an audit
        # entry lands in the same commit as the action it records rather
        # than being a separate, out-of-band write.
        entry = AuditLog(
            business_id=business_id,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            event_metadata=metadata,
        )
        self.session.add(entry)
        self.session.flush()
        return entry


def record_audit_event(
    db: Session,
    *,
    business_id: uuid.UUID,
    user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict | None = None,
) -> AuditLog:
    """The one call a route/service should use to write an audit entry —
    thin on top of AuditLogRepository, but keeping every call site
    importing a function instead of the repository class is what makes
    "one centralized path" actually enforceable at a glance.
    """
    return AuditLogRepository(db).create(
        business_id=business_id,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
