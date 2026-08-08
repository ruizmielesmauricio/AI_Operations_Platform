"""Offline lat/lon -> IANA timezone lookup via the timezonefinder package
— no network call, no second provider's opinion to reconcile against
Geoapify's own address match. Kept as its own tiny module (not inlined
into service.py) since TimezoneFinder() itself is expensive to construct
(loads a binary boundary-data file) and must be a module-level singleton,
reused across every call — timezonefinder's own docs warn against
constructing a fresh instance per lookup.
"""

from timezonefinder import TimezoneFinder

_finder = TimezoneFinder()


def resolve_timezone(*, lat: float, lon: float) -> str | None:
    """The IANA timezone identifier (e.g. "Europe/Dublin") covering this
    coordinate. timezonefinder's own data covers the whole globe,
    including ocean (as "Etc/GMT+N" nautical zones) — live-verified this
    returns a real zone even far from land, so None in practice only
    happens for a genuinely invalid/out-of-range coordinate, not "no data
    here."
    """
    return _finder.timezone_at(lat=lat, lng=lon)
