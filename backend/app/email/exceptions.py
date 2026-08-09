class EmailNotConfigured(Exception):
    """No RESEND_API_KEY/RESEND_FROM_EMAIL is set. Distinct from
    EmailProviderError — this is a deployment/config gap, not a runtime
    failure (mirrors app/geocoding/exceptions.py::GeocodingNotConfigured).
    """


class EmailProviderError(Exception):
    """Resend itself failed (network error, non-2xx, malformed body).
    Caught by app/email/service.py and turned into a quiet, logged
    failure rather than a raised, unhandled error — sending an invite
    email must never block creating the employee seat itself, the same
    PR-5.4-style graceful-degradation posture already used for the AI
    provider gateway and Geoapify.
    """
