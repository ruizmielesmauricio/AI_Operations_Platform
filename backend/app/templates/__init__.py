"""Business template definitions — industry-specific terminology and
configuration that plugs into the shared core and canonical entities without
changing them, per 06_Database_Design.md's three-layer model. Keeps
industry-specific logic out of core services, per CLAUDE.md.

Bike shops are the first commercial vertical (BD-001), not the only one
(BD-002): this registry is the single place that lists which business types
a new account can choose, and what each one switches on. Core code asks a
capability question (``template_supports_repairs``) rather than comparing
against a specific industry's key.

Adding a vertical is a new entry here. Every type gets the shared core
(sales, stock, purchases, suppliers, forecasting, findings, ORLA); a type's
flags only switch on extra modules. Food & drink types use that same core
today — recipe/ingredient costing (production_events inputs/outputs,
ADR-016) is a later module, not a prerequisite. Pharmacy is deliberately not
offered yet: prescription data is GDPR special-category (Q-053, PD-010).
"""

from dataclasses import dataclass

DEFAULT_TEMPLATE_KEY = "bicycle_shop"

GROUP_RETAIL = "Retail"
GROUP_FOOD_AND_DRINK = "Food & drink"


@dataclass(frozen=True)
class BusinessTemplate:
    key: str
    label: str
    description: str
    # Display grouping in the signup dropdown.
    group: str
    # Repairs/service jobs (production_events, event_type="repair") — drives
    # the repairs upload type, Workshop Performance, and repair search.
    supports_repairs: bool = False


def _retail(key: str, label: str, description: str, *, repairs: bool = False) -> BusinessTemplate:
    return BusinessTemplate(key, label, description, GROUP_RETAIL, repairs)


def _food(key: str, label: str, description: str) -> BusinessTemplate:
    return BusinessTemplate(key, label, description, GROUP_FOOD_AND_DRINK)


_REPAIRS = "Sales, stock, purchases and suppliers, plus repairs and servicing."
_RETAIL = "Sales, stock, purchases and suppliers."
_FOOD = "Sales, stock, purchases and suppliers for food & drink."

# Order here is the order shown at signup.
_TEMPLATES: tuple[BusinessTemplate, ...] = (
    # --- Retail ---
    _retail("bicycle_shop", "Bike shop", _REPAIRS, repairs=True),
    _retail("general_retail", "General retail / gift shop", _RETAIL),
    _retail("clothing_fashion", "Clothing, shoes & accessories", _RETAIL),
    _retail("electronics_phones", "Electronics & phone shop", _REPAIRS, repairs=True),
    _retail("outdoor_sports", "Outdoor & sports shop", _REPAIRS, repairs=True),
    _retail("hardware_diy", "Hardware & DIY", _RETAIL),
    _retail("books_stationery", "Books & stationery", _RETAIL),
    _retail("toys_games", "Toys & games", _RETAIL),
    _retail("pet_shop", "Pet shop", _RETAIL),
    _retail("garden_centre", "Garden centre", _RETAIL),
    _retail("convenience_grocery", "Convenience store & grocery", _RETAIL),
    _retail("jewellery_watches", "Jewellery & watches", _REPAIRS, repairs=True),
    _retail("retail_with_workshop", "Other shop with a repair or service workshop", _REPAIRS, repairs=True),
    # --- Food & drink ---
    _food("cafe", "Café / coffee shop", _FOOD),
    _food("restaurant", "Restaurant", _FOOD),
    _food("bakery", "Bakery", _FOOD),
    _food("bar_pub", "Bar / pub", _FOOD),
    _food("takeaway", "Takeaway / fast food", _FOOD),
    _food("deli_food_shop", "Deli / speciality food shop", _FOOD),
)

_BY_KEY: dict[str, BusinessTemplate] = {t.key: t for t in _TEMPLATES}

TEMPLATE_KEYS: frozenset[str] = frozenset(_BY_KEY)


def list_templates() -> tuple[BusinessTemplate, ...]:
    return _TEMPLATES


def get_template(key: str) -> BusinessTemplate | None:
    return _BY_KEY.get(key)


def template_label(key: str) -> str:
    """Display name for a stored template key; falls back to the raw key for
    any legacy value no longer in the registry, rather than failing."""
    template = _BY_KEY.get(key)
    return template.label if template else key


def template_supports_repairs(key: str) -> bool:
    template = _BY_KEY.get(key)
    return bool(template and template.supports_repairs)
