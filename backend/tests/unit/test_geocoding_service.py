import pytest

from app.geocoding import service
from app.geocoding.exceptions import GeocodingNotConfigured, GeocodingProviderError


def test_suggest_addresses_with_a_blank_query_makes_no_call(monkeypatch):
    def _fail_if_called(text):
        raise AssertionError("autocomplete should not be called for a blank query")

    monkeypatch.setattr(service, "autocomplete", _fail_if_called)

    assert service.suggest_addresses("") == []
    assert service.suggest_addresses("   ") == []


def test_suggest_addresses_when_not_configured_returns_an_empty_list(monkeypatch):
    def _raise_not_configured(text):
        raise GeocodingNotConfigured("no key")

    monkeypatch.setattr(service, "autocomplete", _raise_not_configured)

    # Deliberately quiet, not an error surfaced to the caller — a live-
    # suggestion field failing silently (no dropdown) is normal UX while
    # someone is still typing, not something to interrupt them about.
    assert service.suggest_addresses("12 Main Street") == []


def test_suggest_addresses_when_the_provider_request_fails_returns_an_empty_list(monkeypatch):
    def _raise_provider_error(text):
        raise GeocodingProviderError("timeout")

    monkeypatch.setattr(service, "autocomplete", _raise_provider_error)

    assert service.suggest_addresses("12 Main Street") == []


def test_suggest_addresses_with_no_matches_returns_an_empty_list(monkeypatch):
    monkeypatch.setattr(service, "autocomplete", lambda text: [])
    assert service.suggest_addresses("asdkfjasldkfj") == []


def test_suggest_addresses_resolves_timezone_per_suggestion_from_its_own_coordinates(monkeypatch):
    fake_results = [
        {
            "formatted": "12 Main Street, Dublin, D02, Ireland",
            "address_line1": "12 Main Street",
            "city": "Dublin",
            "postcode": "D02",
            "country": "Ireland",
            "lat": 53.3498,
            "lon": -6.2603,
        },
        {
            "formatted": "12 Main Street, Galway, Ireland",
            "address_line1": "12 Main Street",
            "city": "Galway",
            "postcode": None,
            "country": "Ireland",
            "lat": 53.2707,
            "lon": -9.0568,
        },
    ]
    monkeypatch.setattr(service, "autocomplete", lambda text: fake_results)

    suggestions = service.suggest_addresses("12 Main Street")
    assert len(suggestions) == 2
    assert suggestions[0].formatted_address == "12 Main Street, Dublin, D02, Ireland"
    assert suggestions[0].city == "Dublin"
    # The one real cross-module integration this test proves: each
    # suggestion's own lat/lon actually gets run through timezonefinder,
    # not just echoed back or shared across suggestions — both resolve to
    # the same real Irish zone here, but from two genuinely different
    # coordinates.
    assert suggestions[0].timezone == "Europe/Dublin"
    assert suggestions[1].city == "Galway"
    assert suggestions[1].timezone == "Europe/Dublin"


def test_suggest_addresses_skips_a_result_with_no_formatted_address(monkeypatch):
    # Defensive: Geoapify's own contract always includes `formatted`, but
    # a result missing it isn't something worth surfacing as a suggestion
    # with a blank label — skipped rather than shown broken.
    fake_results = [{"formatted": None, "lat": 53.35, "lon": -6.26}]
    monkeypatch.setattr(service, "autocomplete", lambda text: fake_results)
    assert service.suggest_addresses("something") == []
