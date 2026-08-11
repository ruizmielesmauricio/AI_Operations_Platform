"""Shared plain-text formatting helpers for the PDF/DOCX report
exporters (app/exports/pdf.py, app/exports/docx.py) — both read from the
exact same already-computed, already-stored Report.payload dict (no new
calculation, per CLAUDE.md's Core Rule; see app/application/report.py's
own _assemble_payload). Mirrors frontend/lib/format.ts's formatMoney/
formatPct conventions so a number reads identically whether it's seen on
the dashboard, in the app/reports/[id] page, or in a downloaded file.
"""

from decimal import Decimal, InvalidOperation


def safe_str(value: object, default: str = "—") -> str:
    if value is None:
        return default
    return str(value)


def format_money(value: object) -> str:
    if value is None:
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    return f"€{amount:,.2f}"


def format_pct(value: object) -> str:
    if value is None:
        return "—"
    return f"{value}%"


def safe_get(payload: dict, *path: str, default=None):
    node = payload
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return default if node is None else node
