from app.geocoding.timezone_lookup import resolve_timezone


def test_resolve_timezone_for_dublin():
    assert resolve_timezone(lat=53.3498, lon=-6.2603) == "Europe/Dublin"


def test_resolve_timezone_for_new_york():
    assert resolve_timezone(lat=40.7128, lon=-74.0060) == "America/New_York"


def test_resolve_timezone_for_galway():
    assert resolve_timezone(lat=53.2707, lon=-9.0568) == "Europe/Dublin"


def test_resolve_timezone_covers_open_ocean_via_nautical_zones():
    # timezonefinder's own data covers the whole globe, not just land —
    # open ocean resolves to one of the "Etc/GMT+N" nautical zones rather
    # than None. Verified live before writing this assertion; the
    # service.py docstring's "None if it falls outside any known
    # boundary" case is a real, typed possibility per timezonefinder's
    # own API, just not one either of these two real coordinates hits.
    assert resolve_timezone(lat=0.0, lon=-150.0) == "Etc/GMT+10"
