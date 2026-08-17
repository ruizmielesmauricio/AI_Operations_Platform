"""Covers app/email/service.py::send_employee_invite_email — the actual
message content (direct request: a clear, branded, correct message that
tells the employee the signup link already has their email filled in and
that they only need to choose a password), the HTML-escaping of every
interpolated value, and the three outcomes (sent / not configured /
provider error) already relied on elsewhere but never directly tested.
"""

from app.email import client
from app.email.exceptions import EmailNotConfigured, EmailProviderError
from app.email.service import send_employee_invite_email


def test_invite_email_subject_and_body_mention_the_business_and_orla(monkeypatch):
    captured = {}

    def fake_send_email(*, to, subject, html):
        captured["to"] = to
        captured["subject"] = subject
        captured["html"] = html
        return {"id": "email_1"}

    monkeypatch.setattr(client, "send_email", fake_send_email)

    sent = send_employee_invite_email(
        to_email="new-staff@example.com", business_name="Test Bike Shop",
        registration_url="https://app.example.com/signup?email=new-staff%40example.com",
    )

    assert sent is True
    assert "ORLA" in captured["subject"]
    assert "Test Bike Shop" in captured["subject"]
    assert "new-staff@example.com" in captured["html"]
    assert "https://app.example.com/signup?email=new-staff%40example.com" in captured["html"]


def test_invite_email_body_tells_the_employee_the_email_is_already_filled_in(monkeypatch):
    # Direct request: the message must actually say the signup link's
    # email field is prefilled, not leave the employee to guess whether
    # they need to retype it — this is what frontend/app/signup/page.tsx's
    # own `?email=` prefill (task #158) is for.
    captured = {}
    monkeypatch.setattr(client, "send_email", lambda **kwargs: captured.update(kwargs) or {"id": "email_1"})

    send_employee_invite_email(
        to_email="staff@example.com", business_name="Test Bike Shop",
        registration_url="https://app.example.com/signup?email=staff%40example.com",
    )

    assert "already has your email address" in captured["html"]
    assert "choose a password" in captured["html"]


def test_invite_email_escapes_html_special_characters_in_business_name(monkeypatch):
    # Live-relevant, not theoretical: business_name is whatever the owner
    # typed into the Company Profile form — must never be spliced into
    # the email's HTML unescaped.
    captured = {}
    monkeypatch.setattr(client, "send_email", lambda **kwargs: captured.update(kwargs) or {"id": "email_1"})

    send_employee_invite_email(
        to_email="staff@example.com", business_name="Bikes & <Repairs>",
        registration_url="https://app.example.com/signup?email=staff%40example.com",
    )

    assert "<Repairs>" not in captured["html"]
    assert "Bikes &amp; &lt;Repairs&gt;" in captured["html"]


def test_invite_email_not_configured_returns_false_without_raising(monkeypatch):
    def fail(*args, **kwargs):
        raise EmailNotConfigured("RESEND_API_KEY/RESEND_FROM_EMAIL are not set")

    monkeypatch.setattr(client, "send_email", fail)

    sent = send_employee_invite_email(
        to_email="staff@example.com", business_name="Test Bike Shop", registration_url="https://app.example.com/signup"
    )

    assert sent is False


def test_invite_email_provider_error_returns_false_without_raising(monkeypatch):
    def fail(*args, **kwargs):
        raise EmailProviderError("Resend returned a non-2xx response")

    monkeypatch.setattr(client, "send_email", fail)

    sent = send_employee_invite_email(
        to_email="staff@example.com", business_name="Test Bike Shop", registration_url="https://app.example.com/signup"
    )

    assert sent is False
