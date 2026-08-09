"""Orchestrates address validation for a route: turns the free-text
address the owner is typing into live suggestions (Geoapify's
autocomplete endpoint via app/geocoding/client.py), each resolved to an
IANA timezone (app/geocoding/timezone_lookup.py) up front so picking one
needs no second round trip. No calculation logic of its own — same "thin
orchestration over pure/boundary pieces" shape as every
app/application/*.py module, per CLAUDE.md.

Direct request: live suggestions as the owner types (like any modern
address field), not a single click-to-validate action. A short client-
side debounce (frontend/app/onboarding/[id]/page.tsx) keeps request
volume bounded against Geoapify's free-tier cap — this module itself
makes exactly one HTTP call per invocation regardless.
"""

from dataclasses import dataclass

from app.geocoding.client import autocomplete
from app.geocoding.exceptions import GeocodingNotConfigured, GeocodingProviderError
from app.geocoding.timezone_lookup import resolve_timezone


@dataclass(frozen=True)
class AddressSuggestion:
    formatted_address: str
    address_line1: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None
    # Derived locally via timezonefinder from this specific suggestion's
    # own coordinate — resolved for every suggestion up front (cheap,
    # offline) so clicking one needs no further request.
    timezone: str | None = None


def suggest_addresses(text: str) -> list[AddressSuggestion]:
    """Empty list for a blank/too-short query, when address validation
    isn't configured, when the provider request itself fails, or when
    nothing matches yet — deliberately never an error to the caller for
    any of these: a live-suggestion field failing quietly (no dropdown)
    is the normal, expected behavior of this kind of UI while someone is
    still typing, not something to interrupt them about. Provider
    failures are logged by app/geocoding/client.py's own caller
    (app/api/businesses.py) if ever needed for diagnosis; this function
    itself stays silent on purpose.
    """
    query = (text or "").strip()
    if not query:
        return []

    try:
        results = autocomplete(query)
    except (GeocodingNotConfigured, GeocodingProviderError):
        return []

    suggestions = []
    for result in results:
        formatted = result.get("formatted")
        if not formatted:
            continue
        lat, lon = result.get("lat"), result.get("lon")
        timezone = resolve_timezone(lat=lat, lon=lon) if lat is not None and lon is not None else None
        suggestions.append(
            AddressSuggestion(
                formatted_address=formatted,
                address_line1=result.get("address_line1") or result.get("street"),
                city=result.get("city"),
                postal_code=result.get("postcode"),
                country=result.get("country"),
                timezone=timezone,
            )
        )
    return suggestions
