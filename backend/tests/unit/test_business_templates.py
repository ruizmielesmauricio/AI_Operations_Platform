import pytest
from pydantic import ValidationError

from app.schemas.business import BusinessCreate
from app.templates import (
    DEFAULT_TEMPLATE_KEY,
    TEMPLATE_KEYS,
    get_template,
    list_templates,
    template_label,
    template_supports_repairs,
)


def test_more_than_one_business_type_is_offered():
    # Bike shops are the first vertical, not the only one (BD-002).
    assert len(list_templates()) > 1
    assert any(not t.supports_repairs for t in list_templates())


def test_default_template_is_registered():
    assert DEFAULT_TEMPLATE_KEY in TEMPLATE_KEYS
    assert get_template(DEFAULT_TEMPLATE_KEY) is not None


def test_template_keys_are_unique():
    keys = [t.key for t in list_templates()]
    assert len(keys) == len(set(keys))


def test_supports_repairs_by_template():
    assert template_supports_repairs("bicycle_shop") is True
    assert template_supports_repairs("retail_with_workshop") is True
    assert template_supports_repairs("general_retail") is False
    assert template_supports_repairs("cafe") is False
    assert template_supports_repairs("restaurant") is False


def test_retail_and_food_and_drink_are_both_offered():
    groups = {t.group for t in list_templates()}
    assert {"Retail", "Food & drink"} <= groups
    assert {"cafe", "restaurant", "general_retail", "bicycle_shop"} <= TEMPLATE_KEYS


def test_pharmacy_not_offered_until_gdpr_review():
    # Prescription data is GDPR special-category (Q-053) — not offered yet.
    assert "pharmacy" not in TEMPLATE_KEYS


def test_unknown_template_has_no_repairs_and_falls_back_to_raw_label():
    assert template_supports_repairs("legacy_unknown") is False
    assert template_label("legacy_unknown") == "legacy_unknown"
    assert template_label("cafe") == "Café / coffee shop"


@pytest.mark.parametrize("key", sorted(TEMPLATE_KEYS))
def test_business_create_accepts_every_registered_template(key):
    assert BusinessCreate(name="Shop", template=key).template == key


def test_business_create_rejects_unknown_template():
    with pytest.raises(ValidationError):
        BusinessCreate(name="Shop", template="spaceship_dealer")


def test_business_create_defaults_to_registered_template():
    assert BusinessCreate(name="Shop").template == DEFAULT_TEMPLATE_KEY


def test_business_create_rejects_unknown_timezone():
    with pytest.raises(ValidationError):
        BusinessCreate(name="Shop", timezone="Europe/Dubln")


def test_business_create_accepts_real_timezone():
    assert BusinessCreate(name="Shop", timezone="Europe/Dublin").timezone == "Europe/Dublin"


def test_profile_update_rejects_unknown_timezone_but_allows_omitting_it():
    from app.schemas.business import BusinessProfileUpdate

    with pytest.raises(ValidationError):
        BusinessProfileUpdate(timezone="Mars/Olympus")
    assert BusinessProfileUpdate(city="Cork").timezone is None
