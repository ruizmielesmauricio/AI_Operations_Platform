"""Orchestrates the one transactional email this app sends so far: the
employee-seat invite (PD-employee-seats). No calculation logic of its
own — same "thin orchestration over a provider boundary" shape as
app/geocoding/service.py.
"""

import logging

from app.email import client
from app.email.exceptions import EmailNotConfigured, EmailProviderError

logger = logging.getLogger(__name__)


def send_employee_invite_email(*, to_email: str, business_name: str, registration_url: str) -> bool:
    """Never raises — a failed or not-yet-configured invite email must
    never block creating the employee seat itself (the owner can always
    tell the employee to sign up directly; the email is a courtesy, not
    the only path to registration, since reconciliation
    (app/application/employee_seats.py::reconcile_pending_employee_seats)
    already links by email match regardless of how the employee found
    their way to /signup). Returns whether it actually sent.
    """
    subject = f"You've been added to {business_name} on AI Operations Platform"
    html = (
        f"<p>You've been added as a team member on <strong>{business_name}</strong>.</p>"
        f"<p>Finish setting up your account to get access: "
        f'<a href="{registration_url}">{registration_url}</a></p>'
        f"<p>Use this exact email address ({to_email}) when you sign up — that's how your account "
        f"gets connected to {business_name}.</p>"
    )
    try:
        client.send_email(to=to_email, subject=subject, html=html)
        return True
    except EmailNotConfigured:
        # Quiet, not a warning — this is an expected, common state for a
        # dev/prototype deployment with no RESEND_API_KEY set yet, same
        # posture as Geoapify's "not configured" path.
        logger.info("Invite email not sent (email provider not configured): to=%s", to_email)
        return False
    except EmailProviderError as exc:
        logger.warning("Invite email failed to send: to=%s error=%s", to_email, exc)
        return False
