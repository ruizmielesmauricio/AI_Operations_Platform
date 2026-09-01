"""Best-effort value parsers used only for structural-heuristics scoring
(app/imports/detection.py) — i.e. "does this column look like a date?",
not final data normalisation. Actual row-level normalisation with strict
correctness guarantees is B8's job (PR-2.6).
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y",
    "%d/%m/%y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%d %B %Y", "%b %d, %Y",
    "%B %d, %Y",
)

_CURRENCY_RE = re.compile(r"[£$€]")
_CURRENCY_CODE_RE = re.compile(r"\b(?:EUR|GBP|USD)\b", re.I)


def parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = _CURRENCY_CODE_RE.sub("", _CURRENCY_RE.sub("", value.strip()))
    negative = text.startswith("-") or text.endswith("-")
    text = text.strip("-").strip()
    if not text:
        return None

    last_comma, last_dot = text.rfind(","), text.rfind(".")
    if last_comma == -1 and last_dot == -1:
        digits = text
    elif last_comma > last_dot:
        # Comma is the decimal separator (e.g. "1.234,56"); dots are
        # thousands separators.
        digits = text.replace(".", "").replace(",", ".")
    else:
        # Dot is the decimal separator (e.g. "1,234.56"); commas are
        # thousands separators.
        digits = text.replace(",", "")

    try:
        result = Decimal(digits)
    except InvalidOperation:
        return None
    return -result if negative else result


def parse_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(",", "")
    try:
        as_float = float(text)
    except ValueError:
        return None
    return int(as_float) if as_float.is_integer() else None
