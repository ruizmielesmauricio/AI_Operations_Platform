"""How long a generated report stays available to a customer (PR-8.5 /
ADR-019: seven days after generation, weekly and monthly alike). Pure — no
DB, no FastAPI — so the countdown is unit-testable on its own and computed
once, server-side, rather than from each browser's own clock.
"""

from datetime import datetime, timezone

# Within this many seconds of expiry a report is "expiring soon" — the UI
# switches its countdown to a warning style. Two days: enough time to
# download a PDF/DOCX copy before the report disappears from the list.
EXPIRING_SOON_SECONDS = 2 * 24 * 3600


def seconds_until_expiry(expires_at: datetime | None, *, now: datetime | None = None) -> int | None:
    """Whole seconds remaining before `expires_at`, never negative (an
    already-expired report reads 0, not a negative countdown). None when
    the report has no expiry at all (e.g. a row that isn't completed yet).
    """
    if expires_at is None:
        return None
    resolved_now = now or datetime.now(timezone.utc)
    # SQLite (used in tests) round-trips DateTime(timezone=True) as naive
    # datetimes even though every stored value is UTC — normalize, same as
    # app/api/reports.py::_as_aware_utc.
    aware_expiry = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=timezone.utc)
    return max(0, int((aware_expiry - resolved_now).total_seconds()))


def is_expiring_soon(seconds_remaining: int | None) -> bool:
    return seconds_remaining is not None and seconds_remaining <= EXPIRING_SOON_SECONDS
