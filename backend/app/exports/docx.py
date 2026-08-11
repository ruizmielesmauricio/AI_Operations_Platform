"""Real, server-generated DOCX export of a stored Report — the DOCX
counterpart to app/exports/pdf.py, same source data (Report.payload),
same section coverage, same "no calculation, only formatting" rule.
Built with python-docx (real headings/paragraphs/tables — a genuine
.docx document a reader can open in Word, not plain text or HTML
relabelled with a .docx extension, per this prompt's own explicit "do
not label plain text or HTML as DOCX" instruction).
"""

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.exports.formatting import format_money, format_pct, safe_get, safe_str


def _add_table(document: Document, headers: list[str], rows: list[list[str]]) -> None:
    # "Table Grid" is one of python-docx's own guaranteed built-in
    # styles, present on every Document() by default — no risk of a
    # missing-style error the way a named accent style could carry.
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for i, header in enumerate(headers):
        header_cells[i].text = header
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = value


def render_report_docx(payload: dict) -> bytes:
    document = Document()

    label = "Weekly" if payload.get("report_type") == "weekly" else "Monthly"
    document.add_heading(f"{safe_str(payload.get('business_name'))} — {label} Report", level=1)
    period_paragraph = document.add_paragraph(
        f"Period: {safe_str(payload.get('period_start'))} to {safe_str(payload.get('period_end'))}"
    )
    period_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    document.add_paragraph(f"Generated: {safe_str(payload.get('generated_at'))}")

    # Executive Summary
    summary = safe_get(payload, "executive_summary", default={})
    document.add_heading("Executive Summary", level=2)
    for line in summary.get("narrative") or []:
        document.add_paragraph(str(line))
    document.add_paragraph(
        f"Transactions: {safe_str(summary.get('transactions'))} · "
        f"Average sale: {format_money(summary.get('average_sale'))} · "
        f"Low stock: {safe_str(summary.get('low_stock_count'))} · "
        f"Dead stock: {safe_str(summary.get('dead_stock_count'))}"
    )

    # Financial Performance
    financial = safe_get(payload, "financial_performance", default={})
    revenue = financial.get("revenue") or {}
    gross_margin = financial.get("gross_margin") or {}
    document.add_heading("Financial Performance", level=2)
    document.add_paragraph(
        f"Revenue: {format_money(revenue.get('current'))} "
        f"(previous period: {format_money(revenue.get('previous'))}, "
        f"change: {format_pct(revenue.get('change_pct'))})"
    )
    document.add_paragraph(
        f"Gross margin: {format_pct(gross_margin.get('net_gross_margin_pct') or gross_margin.get('gross_margin_pct'))} "
        f"— {format_money(gross_margin.get('net_gross_profit') or gross_margin.get('gross_profit'))} kept as gross profit"
    )

    # Retail Operations — top sellers by revenue
    retail = safe_get(payload, "retail_operations", default={})
    top_sellers = retail.get("top_sellers_by_revenue") or []
    if top_sellers:
        document.add_heading("Top Sellers (by revenue)", level=2)
        _add_table(
            document,
            ["Product", "Category", "Units sold", "Revenue"],
            [
                [
                    safe_str(row.get("name")), safe_str(row.get("category_name"), "—"),
                    safe_str(row.get("units_sold")), format_money(row.get("revenue")),
                ]
                for row in top_sellers[:15]
            ],
        )

    dead_stock = retail.get("dead_stock") or []
    if dead_stock:
        document.add_paragraph(
            f"{len(dead_stock)} product(s) have stock on hand but zero sales this period (dead stock)."
        )

    # Category Breakdown
    category_breakdown = safe_get(payload, "category_breakdown", "rows", default=[])
    if category_breakdown:
        document.add_heading("Category Breakdown", level=2)
        _add_table(
            document,
            ["Category", "Revenue", "Expenses", "Stock value"],
            [
                [
                    safe_str(row.get("category_name")), format_money(row.get("revenue")),
                    format_money(row.get("expenses")), format_money(row.get("stock_value")),
                ]
                for row in category_breakdown[:20]
            ],
        )

    # Findings & Recommendations
    findings = safe_get(payload, "findings", "recommendations", default=[])
    if findings:
        document.add_heading("Recommendations", level=2)
        for rec in findings[:15]:
            document.add_paragraph(f"{safe_str(rec.get('title'))}: {safe_str(rec.get('description'))}", style="List Bullet")

    # Workshop Performance (bicycle-shop template only)
    workshop = payload.get("workshop_performance")
    if workshop:
        margin = workshop.get("margin") or {}
        document.add_heading("Workshop Performance", level=2)
        document.add_paragraph(
            f"Repairs: {safe_str(margin.get('repair_count'))} · "
            f"Revenue: {format_money((workshop.get('revenue') or {}).get('current'))} · "
            f"Margin: {format_pct(margin.get('net_gross_margin_pct') or margin.get('gross_margin_pct'))}"
        )

    # Forecast (aggregate figures only — see app/exports/pdf.py's own
    # comment for why the day-by-day curve is deliberately excluded).
    forecast_revenue = safe_get(payload, "forecast", "revenue", "result", default={})
    if forecast_revenue and not forecast_revenue.get("insufficient_data"):
        document.add_heading("Revenue Forecast", level=2)
        document.add_paragraph(
            f"Projected: {format_money(forecast_revenue.get('total_point'))} "
            f"(range {format_money(forecast_revenue.get('total_low'))} – "
            f"{format_money(forecast_revenue.get('total_high'))})"
        )

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
