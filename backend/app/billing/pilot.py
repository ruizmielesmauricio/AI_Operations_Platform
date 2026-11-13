"""Free pilot window check — dependency-free (no FastAPI/auth imports) so
any layer can use it without import cycles. See app/billing/access.py."""

from datetime import datetime, timezone

from app.models.business import Business


def _as_aware(value: datetime) -> datetime:
    # SQLite (tests) hands back naive datetimes; Postgres returns aware ones.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def pilot_access_active(business: Business | None, now: datetime | None = None) -> bool:
    if business is None or business.pilot_access_until is None:
        return False
    return _as_aware(business.pilot_access_until) > (now or datetime.now(timezone.utc))
