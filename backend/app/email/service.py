"""Orchestrates the one transactional email this app sends so far: the
employee-seat invite (PD-employee-seats). No calculation logic of its
own — same "thin orchestration over a provider boundary" shape as
app/geocoding/service.py.
"""

import html as html_lib
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

    `registration_url` already carries `?email={to_email}` (built by the
    caller) — frontend/app/signup/page.tsx reads that query param and
    prefills the email field on load (still fully editable, just saves
    retyping it), so the message here says so plainly rather than
    leaving the employee to guess whether they need to type it in
    themselves. Inline-styled HTML (no external CSS/JS) since email
    clients strip both — mirrors the brand mark/colors
    frontend/app/globals.css's own `.auth-brand`/`--app-green` already
    use on every real login/signup page, so this doesn't look like a
    different product. Every interpolated value is HTML-escaped —
    business_name and to_email both ultimately come from what the owner
    typed into a form, never assumed safe to splice into markup as-is.
    """
    safe_business_name = html_lib.escape(business_name)
    safe_to_email = html_lib.escape(to_email)
    safe_registration_url = html_lib.escape(registration_url, quote=True)

    subject = f"You're invited to join {business_name} on ORLA"
    html = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;">
  <div style="display: inline-flex; align-items: center; gap: 8px; margin-bottom: 24px;">
    <span style="display: inline-block; width: 28px; height: 28px; line-height: 28px; text-align: center; border-radius: 5px; background: #24765a; color: #fff; font-weight: 800; font-size: 13px;">OR</span>
    <span style="font-weight: 800; font-size: 16px; color: #1b1e1f;">ORLA</span>
  </div>
  <p style="color: #1b1e1f; font-size: 15px; line-height: 1.5;">
    You've been added as a team member on <strong>{safe_business_name}</strong>.
  </p>
  <p style="color: #1b1e1f; font-size: 15px; line-height: 1.5;">
    Set up your account to get started — the link below already has your email address
    (<strong>{safe_to_email}</strong>) filled in, so you'll just need to choose a password.
  </p>
  <p style="margin: 28px 0;">
    <a href="{safe_registration_url}" style="display: inline-block; background: #24765a; color: #fff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 700; font-size: 15px;">
      Set up your ORLA account
    </a>
  </p>
  <p style="color: #69716c; font-size: 13px; line-height: 1.5;">
    If the button above doesn't work, copy this link into your browser: {safe_registration_url}
  </p>
  <p style="color: #69716c; font-size: 13px; line-height: 1.5;">
    If you weren't expecting this, you can safely ignore this email.
  </p>
</div>
"""
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
