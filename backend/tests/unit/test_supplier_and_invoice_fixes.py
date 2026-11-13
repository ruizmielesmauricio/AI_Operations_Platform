from types import SimpleNamespace

from app.imports.importer import SupplierMatcher
from app.invoices.extraction import _LABEL_PATTERNS


def _s(name):
    return SimpleNamespace(id=name, name=name)


def test_supplier_matches_ignoring_company_suffix():
    # Live: "Parts Hub Ireland Ltd" on an invoice proposed a duplicate supplier.
    matcher = SupplierMatcher([_s("Parts Hub Ireland")])
    assert matcher.resolve("Parts Hub Ireland Ltd").name == "Parts Hub Ireland"
    assert matcher.resolve("parts hub ireland limited.").name == "Parts Hub Ireland"


def test_supplier_suffix_match_never_guesses_between_two():
    matcher = SupplierMatcher([_s("Acme Ltd"), _s("Acme Limited")])
    assert matcher.resolve("Acme") is None  # two suppliers share the base name: no guess
    assert matcher.resolve("Acme PLC") is None


def test_exact_supplier_name_still_wins():
    matcher = SupplierMatcher([_s("Velo Distributors"), _s("Velo")])
    assert matcher.resolve("Velo").name == "Velo"


def _tax(text):
    for pattern in _LABEL_PATTERNS["tax_total"]:
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
    return None


def test_vat_registration_number_is_not_read_as_tax_total():
    # Live: "VAT No: IE0000000TEST" claimed the tax total.
    assert _tax("VAT No: IE0000000TEST") is None
    assert _tax("VAT Number IE1234567X") is None


def test_vat_line_with_rate_is_read():
    assert _tax("VAT 23%: EUR 151.43") == "EUR 151.43"
    assert _tax("VAT: 12.00") == "12.00"
    assert _tax("Tax total: 5.00") == "5.00"
