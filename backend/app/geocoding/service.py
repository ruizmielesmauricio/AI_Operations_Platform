"""Orchestrates address validation for a route: combines the free-text
address fields into one query, calls Geoapify (app/geocoding/client.py),
and resolves the matched coordinate to an IANA timezone
(app/geocoding/timezone_lookup.py). No calculation logic of its own —
same "thin orchestration over pure/boundary pieces" shape as every
app/application/*.py module, per CLAUDE.md.

Deliberately explicit-action, not autocomplete-as-you-type: this is
called once, when an owner clicks "Validate address" while editing a
business's profile — not on every keystroke. Geoapify's free tier is
capped at 3,000 requests/day, and editing a business profile is an
infrequent action; there's no case here for the request volume an
autocomplete widget would generate.
"""

from dataclasses import dataclass

from app.geocoding.client import geocode
from app.geocoding.exceptions import GeocodingNotConfigured, GeocodingProviderError
from app.geocoding.timezone_lookup import resolve_timezone


@dataclass(frozen=True)
class AddressValidationResult:
    matched: bool
    # Human-readable reason when matched is False — "not configured" /
    # "no match found" / "the provider request failed" — so the frontend
    # can show something honest instead of a bare "invalid address."
    reason: str | None
    # Geoapify's own normalized fields, only present when matched.
    formatted_address: str | None = None
    address_line1: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None
    # 0-1, Geoapify's own confidence score for the match, when it supplies
    # one — surfaced so a low-confidence match can be shown as "please
    # double-check this" rather than presented with the same certainty as
    # an exact match.
    confidence: float | None = None
    # Derived locally via timezonefinder. timezonefinder's own data covers
    # the whole globe including ocean (via "Etc/GMT+N" nautical zones), so
    # in practice this is only ever None when lat/lon themselves weren't
    # available on the geocoded result at all.
    timezone: str | None = None


def validate_address(
    *, address_line1: str | None, city: str | None, postal_code: str | None, country: str | None
) -> AddressValidationResult:
    query = ", ".join(part for part in [address_line1, city, postal_code, country] if part and part.strip())
    if not query:
        return AddressValidationResult(matched=False, reason="No address entered")

    try:
        result = geocode(query)
    except GeocodingNotConfigured:
        return AddressValidationResult(matched=False, reason="Address validation isn't configured yet")
    except GeocodingProviderError:
        return AddressValidationResult(
            matched=False, reason="Could not reach the address validation service — try again shortly"
        )

    if result is None:
        return AddressValidationResult(matched=False, reason="No matching address found")

    lat, lon = result.get("lat"), result.get("lon")
    timezone = resolve_timezone(lat=lat, lon=lon) if lat is not None and lon is not None else None
    rank = result.get("rank") or {}

    return AddressValidationResult(
        matched=True,
        reason=None,
        formatted_address=result.get("formatted"),
        address_line1=result.get("address_line1") or result.get("street"),
        city=result.get("city"),
        postal_code=result.get("postcode"),
        country=result.get("country"),
        confidence=rank.get("confidence"),
        timezone=timezone,
    )
