from datetime import date, datetime
from decimal import Decimal

from app.imports.value_parsers import parse_date, parse_int, parse_money


def test_parse_date_handles_native_datetime_and_date_objects():
    assert parse_date(datetime(2026, 1, 3, 14, 30)) == date(2026, 1, 3)
    assert parse_date(date(2026, 1, 3)) == date(2026, 1, 3)


def test_parse_date_handles_iso_and_common_formats():
    assert parse_date("2026-01-03") == date(2026, 1, 3)
    # Unambiguous (day > 12) so the day-first vs month-first formats can't
    # both match — confirms day/month positions are read correctly.
    assert parse_date("25/12/2026") == date(2026, 12, 25)
    assert parse_date("12-25-2026") == date(2026, 12, 25)


def test_parse_date_returns_none_for_non_dates():
    assert parse_date("not a date") is None
    assert parse_date(None) is None
    assert parse_date(42) is None


def test_parse_money_handles_currency_symbols_and_native_numbers():
    assert parse_money("$12.50") == Decimal("12.50")
    assert parse_money("£9.99") == Decimal("9.99")
    assert parse_money("€1,000.00") == Decimal("1000.00")
    assert parse_money("EUR 1,125.60") == Decimal("1125.60")
    assert parse_money("14.50 GBP") == Decimal("14.50")
    assert parse_money(42) == Decimal("42")
    assert parse_money(42.5) == Decimal("42.5")


def test_parse_money_resolves_decimal_separator_ambiguity():
    # Dot is the decimal separator; comma is a thousands separator.
    assert parse_money("1,234.56") == Decimal("1234.56")
    # Comma is the decimal separator; dot is a thousands separator.
    assert parse_money("1.234,56") == Decimal("1234.56")


def test_parse_money_handles_negative_values():
    assert parse_money("-12.50") == Decimal("-12.50")


def test_parse_money_returns_none_for_non_money():
    assert parse_money("not money") is None
    assert parse_money("") is None
    assert parse_money(None) is None


def test_parse_int_handles_native_and_string_values():
    assert parse_int(3) == 3
    assert parse_int(3.0) == 3
    assert parse_int("10") == 10
    assert parse_int("1,000") == 1000


def test_parse_int_rejects_non_integer_values():
    assert parse_int(3.5) is None
    assert parse_int("9.99") is None
    assert parse_int("not a number") is None
    assert parse_int(None) is None
