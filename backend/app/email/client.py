"""Direct boundary to the Resend REST API — no other module makes an
HTTP call to Resend, mirroring app/geocoding/client.py's own split from
its service.py. No `resend` SDK dependency: this app already depends on
httpx for every other provider boundary (app/ai/client.py, app/geocoding/
client.py), so a plain POST is the smaller footprint.
"""

import httpx

from app.email.exceptions import EmailNotConfigured, EmailProviderError
from app.settings.config import get_settings

_SEND_URL = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 10.0


def send_email(*, to: str, subject: str, html: str) -> dict:
    """Raises EmailNotConfigured if RESEND_API_KEY/RESEND_FROM_EMAIL
    aren't both set, EmailProviderError for a real request failure
    (network, non-2xx, unparsable body) — both caught by
    app/email/service.py, never left to bubble up as an unhandled 500.
    """
    settings = get_settings()
    if not settings.resend_api_key or not settings.resend_from_email:
        raise EmailNotConfigured("RESEND_API_KEY/RESEND_FROM_EMAIL are not set")

    try:
        response = httpx.post(
            _SEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.resend_from_email, "to": [to], "subject": subject, "html": html},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise EmailProviderError(str(exc)) from exc
    except ValueError as exc:  # response.json() on a non-JSON body
        raise EmailProviderError(f"Resend returned a non-JSON response: {exc}") from exc
