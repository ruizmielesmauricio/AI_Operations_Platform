"""Direct boundary to the Geoapify Geocoding API — no other module makes
an HTTP call to Geoapify, mirroring the app/ai/client.py <-> service.py
and app/billing/client.py <-> service.py splits already used in this
codebase: this file only knows how to make the HTTP request and parse
the response shape; app/geocoding/service.py owns what to do with it.
"""

import httpx

from app.geocoding.exceptions import GeocodingNotConfigured, GeocodingProviderError
from app.settings.config import get_settings

_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
_TIMEOUT_SECONDS = 10.0


def geocode(address_text: str) -> dict | None:
    """The best-matching result for a free-text address query, as
    Geoapify's own raw result dict (lat/lon/formatted/address components/
    rank.confidence — see their docs; not re-shaped here, that's
    service.py's job), or None if nothing matched at all (not an error —
    an address that doesn't resolve is a normal, expected outcome).

    Raises GeocodingNotConfigured if no API key is set, GeocodingProviderError
    for a real request failure (network, non-2xx, unparsable body) — both
    caught by service.py, never left to bubble up as an unhandled 500.
    """
    settings = get_settings()
    if not settings.geoapify_api_key:
        raise GeocodingNotConfigured("GEOAPIFY_API_KEY is not set")

    try:
        response = httpx.get(
            _GEOCODE_URL,
            params={
                "text": address_text,
                "apiKey": settings.geoapify_api_key,
                "format": "json",
                "limit": 1,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        raise GeocodingProviderError(str(exc)) from exc
    except ValueError as exc:  # response.json() on a non-JSON body
        raise GeocodingProviderError(f"Geoapify returned a non-JSON response: {exc}") from exc

    results = body.get("results")
    if not results:
        return None
    return results[0]
