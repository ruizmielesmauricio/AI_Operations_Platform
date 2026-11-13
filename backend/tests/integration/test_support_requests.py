"""The "Contact support" handoff (PR-5.7): a support request is recorded
with an audit event and an owner-only notification, is idempotent per
person/question, rate-limited per business, and optionally emailed to the
ORLA team."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.support_request import SupportRequest
from app.repositories.notification import NotificationRepository
from app.support import service as support_service
from app.support.service import (
    MAX_REQUESTS_PER_BUSINESS_PER_DAY,
    InvalidSupportRequest,
    SupportRequestRateLimited,
    create_support_request,
    email_operator,
    list_support_requests,
    resolve_support_request,
)

_NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)


def _create(db_session, business_id, **overrides):
    fields = dict(
        business_id=business_id, user_id="user-1", requester_email="owner@shop.ie", requester_role="owner",
        question="How do I connect ORLA to my Shopify store?", source="chat", now=_NOW,
    )
    fields.update(overrides)
    request, created = create_support_request(db_session, **fields)
    db_session.commit()
    return request, created


def test_creates_request_audit_event_and_owner_only_notification(db_session, business_id):
    request, created = _create(
        db_session, business_id, requester_role="staff", requester_email="staff@shop.ie", user_id="user-2",
        orla_answer="I couldn't find the answer...", article_slugs=["uploading-your-data", "not-a-real-article"],
    )

    assert created is True
    row = db_session.get(SupportRequest, request.id)
    assert row.business_id == business_id
    assert row.status == "open"
    assert row.question == "How do I connect ORLA to my Shopify store?"
    assert row.requester_email == "staff@shop.ie"
    # Untrusted slugs from the browser are filtered against the knowledge base.
    assert row.article_slugs == ["uploading-your-data"]
    assert row.operator_notified_at is None

    audit = db_session.query(AuditLog).filter_by(action="support_request_created").one()
    assert audit.business_id == business_id and audit.target_id == str(request.id)
    assert "question" not in (audit.event_metadata or {})

    notification = db_session.query(Notification).filter_by(type_key="support_request_created").one()
    assert notification.category == "support"
    assert notification.visible_to_role == "owner"
    assert "staff@shop.ie" in notification.body and "Shopify" in notification.body
    assert notification.action_url.startswith("/help?business=")
    repo = NotificationRepository(db_session)
    assert repo.list_items_for_business(business_id, role="staff") == []
    assert len(repo.list_items_for_business(business_id, role="owner")) == 1


def test_resubmitting_the_same_open_question_is_idempotent(db_session, business_id):
    first, created_first = _create(db_session, business_id)
    second, created_second = _create(db_session, business_id, question="  How do I connect ORLA to my   Shopify store? ")

    assert created_first is True and created_second is False
    assert second.id == first.id
    assert db_session.query(SupportRequest).count() == 1
    assert db_session.query(Notification).count() == 1


def test_rate_limited_per_business_per_day(db_session, business_id):
    for i in range(MAX_REQUESTS_PER_BUSINESS_PER_DAY):
        _create(db_session, business_id, question=f"Question number {i}")
    with pytest.raises(SupportRequestRateLimited):
        _create(db_session, business_id, question="One too many")
    # A day later the window has moved on.
    _, created = _create(db_session, business_id, question="Next day", now=_NOW + timedelta(days=1, minutes=1))
    assert created is True


def test_empty_question_or_unknown_source_is_rejected(db_session, business_id):
    with pytest.raises(InvalidSupportRequest):
        _create(db_session, business_id, question="   ")
    with pytest.raises(InvalidSupportRequest):
        _create(db_session, business_id, source="email")


def test_owner_sees_all_requests_others_see_only_their_own(db_session, business_id):
    _create(db_session, business_id, user_id="owner-1", question="Owner question")
    _create(db_session, business_id, user_id="staff-1", requester_role="staff", question="Staff question")

    owner_view = list_support_requests(db_session, business_id=business_id, user_id="owner-1", role="owner")
    staff_view = list_support_requests(db_session, business_id=business_id, user_id="staff-1", role="staff")

    assert {r.question for r in owner_view} == {"Owner question", "Staff question"}
    assert [r.question for r in staff_view] == ["Staff question"]


def test_operator_email_is_skipped_when_not_configured(db_session, business_id, monkeypatch):
    monkeypatch.setattr(support_service, "get_settings", lambda: SimpleNamespace(support_inbox_email=""))
    request, _ = _create(db_session, business_id)

    assert email_operator(db_session, request) is False
    assert db_session.get(SupportRequest, request.id).operator_notified_at is None


def test_operator_email_marks_the_request_once_sent(db_session, business_id, monkeypatch):
    sent = []
    monkeypatch.setattr(support_service, "get_settings", lambda: SimpleNamespace(support_inbox_email="team@orla.ie"))
    monkeypatch.setattr(support_service, "send_support_request_email", lambda **kw: sent.append(kw) or True)
    request, _ = _create(db_session, business_id)

    assert email_operator(db_session, request) is True
    assert sent[0]["to_email"] == "team@orla.ie"
    assert sent[0]["requester_email"] == "owner@shop.ie"
    assert db_session.get(SupportRequest, request.id).operator_notified_at is not None


def test_operator_can_resolve_a_request(db_session, business_id):
    request, _ = _create(db_session, business_id)

    resolved = resolve_support_request(db_session, request_id=request.id, note="Replied by email", now=_NOW)
    db_session.commit()

    assert resolved.status == "resolved" and resolved.resolution_note == "Replied by email"
    assert db_session.query(AuditLog).filter_by(action="support_request_resolved").count() == 1
