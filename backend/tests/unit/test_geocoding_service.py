import pytest

from app.geocoding import service
from app.geocoding.exceptions import GeocodingNotConfigured, GeocodingProviderError


def test_validate_address_with_no_input_at_all_is_not_matched_and_makes_no_call(monkeypatch):
    def _fail_if_called(query):
        raise AssertionError("geocode should not be called for a blank query")

    monkeypatch.setattr(service, "geocode", _fail_if_called)

    result = service.validate_address(address_line1=None, city=None, postal_code=None, country=None)
    assert result.matched is False
    assert result.reason == "No address entered"


def test_validate_address_when_not_configured(monkeypatch):
    def _raise_not_configured(query):
        raise GeocodingNotConfigured("no key")

    monkeypatch.setattr(service, "geocode", _raise_not_configured)

    result = service.validate_address(address_line1="12 Main Street", city="Dublin", postal_code=None, country=None)
    assert result.matched is False
    assert result.reason == "Address validation isn't configured yet"


def test_validate_address_when_the_provider_request_fails(monkeypatch):
    def _raise_provider_error(query):
        raise GeocodingProviderError("timeout")

    monkeypatch.setattr(service, "geocode", _raise_provider_error)

    result = service.validate_address(address_line1="12 Main Street", city="Dublin", postal_code=None, country=None)
    assert result.matched is False
    assert "try again" in result.reason.lower()


def test_validate_address_with_no_match_found(monkeypatch):
    monkeypatch.setattr(service, "geocode", lambda query: None)

    result = service.validate_address(address_line1="Nonexistent Street", city=None, postal_code=None, country=None)
    assert result.matched is False
    assert result.reason == "No matching address found"


def test_validate_address_with_a_real_match_resolves_timezone_from_coordinates(monkeypatch):
    fake_result = {
        "formatted": "12 Main Street, Dublin, D02, Ireland",
        "address_line1": "12 Main Street",
        "city": "Dublin",
        "postcode": "D02",
        "country": "Ireland",
        "lat": 53.3498,
        "lon": -6.2603,
        "rank": {"confidence": 1.0},
    }
    monkeypatch.setattr(service, "geocode", lambda query: fake_result)

    result = service.validate_address(
        address_line1="12 Main Street", city="Dublin", postal_code="D02", country="Ireland"
    )
    assert result.matched is True
    assert result.formatted_address == "12 Main Street, Dublin, D02, Ireland"
    assert result.city == "Dublin"
    assert result.confidence == 1.0
    # The one real cross-module integration this test proves: a matched
    # result's lat/lon actually gets run through timezonefinder, not just
    # echoed back — Dublin's real coordinates resolve to its real zone.
    assert result.timezone == "Europe/Dublin"


def test_validate_address_builds_one_combined_query_string_from_every_field(monkeypatch):
    captured = {}

    def _capture(query):
        captured["query"] = query
        return None

    monkeypatch.setattr(service, "geocode", _capture)

    service.validate_address(address_line1="12 Main Street", city="Dublin", postal_code="D02", country="Ireland")
    assert captured["query"] == "12 Main Street, Dublin, D02, Ireland"

    # Blank/missing fields are skipped, not turned into empty segments.
    captured.clear()
    service.validate_address(address_line1="12 Main Street", city=None, postal_code=None, country="Ireland")
    assert captured["query"] == "12 Main Street, Ireland"
