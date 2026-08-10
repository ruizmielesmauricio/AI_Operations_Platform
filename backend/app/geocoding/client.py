"""Direct boundary to the Geoapify Geocoding API — no other module makes
an HTTP call to Geoapify, mirroring the app/ai/client.py <-> service.py
and app/billing/client.py <-> service.py splits already used in this
codebase: this file only knows how to make the HTTP request and parse
the response shape; app/geocoding/service.py owns what to do with it.
"""

import httpx

from app.geocoding.exceptions import GeocodingNotConfigured, GeocodingProviderError
from app.settings.config import get_settings

_SEARCH_URL = "https://api.geoapify.com/v1/geocode/search"
_AUTOCOMPLETE_URL = "https://api.geoapify.com/v1/geocode/autocomplete"
_TIMEOUT_SECONDS = 10.0
# Direct request: live-suggestion autocomplete as the owner types, not a
# single best-guess match — this many candidates is enough for a
# type-ahead dropdown without making the response sluggish to render.
_AUTOCOMPLETE_LIMIT = 5


def _get(url: str, *, params: dict) -> dict:
    settings = get_settings()
    if not settings.geoapify_api_key:
        raise GeocodingNotConfigured("GEOAPIFY_API_KEY is not set")

    try:
        response = httpx.get(url, params={**params, "apiKey": settings.geoapify_api_key}, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise GeocodingProviderError(str(exc)) from exc
    except ValueError as exc:  # response.json() on a non-JSON body
        raise GeocodingProviderError(f"Geoapify returned a non-JSON response: {exc}") from exc


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
    body = _get(_SEARCH_URL, params={"text": address_text, "format": "json", "limit": 1})
    results = body.get("results")
    if not results:
        return None
    return results[0]


def autocomplete(text: str) -> list[dict]:
    """Up to _AUTOCOMPLETE_LIMIT partial-match candidates for a still-
    being-typed address, each Geoapify's own raw result dict (same shape
    as geocode's single result) — for a live-suggestion dropdown, not one
    best guess. Empty list if nothing matches yet (normal while the query
    is still short/incomplete, not an error).

    Same exception contract as geocode(): GeocodingNotConfigured/
    GeocodingProviderError, both caught by service.py.
    """
    body = _get(_AUTOCOMPLETE_URL, params={"text": text, "format": "json", "limit": _AUTOCOMPLETE_LIMIT})
    return body.get("results") or []
