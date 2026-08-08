class GeocodingProviderError(Exception):
    """Geoapify itself failed (network error, non-2xx, malformed body) —
    distinct from "the address didn't match anything," which isn't an
    error at all, just an empty result. Caught by app/geocoding/service.py
    and turned into a graceful, honest AddressValidationResult (matched=
    False) rather than a raised, unhandled error — the same PR-5.4-style
    posture already used for AI provider failures in app/ai/client.py.
    """


class GeocodingNotConfigured(Exception):
    """No GEOAPIFY_API_KEY is set. Distinct from GeocodingProviderError —
    this is a deployment/config gap, not a runtime failure, and callers
    may want to say so plainly ("address validation isn't set up yet")
    rather than implying a transient problem.
    """
