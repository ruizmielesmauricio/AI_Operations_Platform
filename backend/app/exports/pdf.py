"""Real, server-generated PDF export of a stored Report (ORLA
Notifications/Security/Retention prompt, section 7) — replaces the
existing "Download PDF" button's browser-print (frontend/app/reports/
[id]/page.tsx, v1.28) with an actual file this route controls end to
end, so permission enforcement doesn't depend on a client ever loading
the page at all. Reads only Report.payload — already fully computed by
app/application/report.py — no calculation of its own (CLAUDE.md's Core
Rule). Not a pixel-identical mirror of the web page; a faithful
representation of the same sections/numbers, via reportlab (pure Python,
no system libraries) rather than an HTML-to-PDF renderer.
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.exports.formatting import format_money, format_pct, safe_get, safe_str

_STYLES = getSampleStyleSheet()
_H1 = ParagraphStyle("ORLAH1", parent=_STYLES["Heading1"], spaceAfter=6)
_H2 = ParagraphStyle("ORLAH2", parent=_STYLES["Heading2"], spaceBefore=14, spaceAfter=6)
_BODY = _STYLES["BodyText"]
_TABLE_HEADER_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
)


def _table(rows: list[list[str]]) -> Table:
    table = Table(rows, repeatRows=1)
    table.setStyle(_TABLE_HEADER_STYLE)
    return table


def render_report_pdf(payload: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.5 * cm, rightMargin=1.5 * cm
    )
    story: list = []

    label = "Weekly" if payload.get("report_type") == "weekly" else "Monthly"
    story.append(Paragraph(f"{safe_str(payload.get('business_name'))} — {label} Report", _H1))
    story.append(
        Paragraph(f"Period: {safe_str(payload.get('period_start'))} to {safe_str(payload.get('period_end'))}", _BODY)
    )
    story.append(Paragraph(f"Generated: {safe_str(payload.get('generated_at'))}", _BODY))

    # Executive Summary
    summary = safe_get(payload, "executive_summary", default={})
    story.append(Paragraph("Executive Summary", _H2))
    for line in summary.get("narrative") or []:
        story.append(Paragraph(str(line), _BODY))
    story.append(
        Paragraph(
            f"Transactions: {safe_str(summary.get('transactions'))} · "
            f"Average sale: {format_money(summary.get('average_sale'))} · "
            f"Low stock: {safe_str(summary.get('low_stock_count'))} · "
            f"Dead stock: {safe_str(summary.get('dead_stock_count'))}",
            _BODY,
        )
    )

    # Financial Performance
    financial = safe_get(payload, "financial_performance", default={})
    revenue = financial.get("revenue") or {}
    gross_margin = financial.get("gross_margin") or {}
    story.append(Paragraph("Financial Performance", _H2))
    story.append(
        Paragraph(
            f"Revenue: {format_money(revenue.get('current'))} "
            f"(previous period: {format_money(revenue.get('previous'))}, "
            f"change: {format_pct(revenue.get('change_pct'))})",
            _BODY,
        )
    )
    story.append(
        Paragraph(
            f"Gross margin: {format_pct(gross_margin.get('net_gross_margin_pct') or gross_margin.get('gross_margin_pct'))} "
            f"— {format_money(gross_margin.get('net_gross_profit') or gross_margin.get('gross_profit'))} kept as gross profit",
            _BODY,
        )
    )

    # Retail Operations — top sellers by revenue
    retail = safe_get(payload, "retail_operations", default={})
    top_sellers = retail.get("top_sellers_by_revenue") or []
    if top_sellers:
        story.append(Paragraph("Top Sellers (by revenue)", _H2))
        rows = [["Product", "Category", "Units sold", "Revenue"]]
        for row in top_sellers[:15]:
            rows.append(
                [
                    safe_str(row.get("name")), safe_str(row.get("category_name"), "—"),
                    safe_str(row.get("units_sold")), format_money(row.get("revenue")),
                ]
            )
        story.append(_table(rows))

    dead_stock = retail.get("dead_stock") or []
    if dead_stock:
        story.append(Spacer(1, 0.3 * cm))
        story.append(
            Paragraph(
                f"{len(dead_stock)} product(s) have stock on hand but zero sales this period (dead stock).", _BODY
            )
        )

    # Category Breakdown
    category_breakdown = safe_get(payload, "category_breakdown", "rows", default=[])
    if category_breakdown:
        story.append(Paragraph("Category Breakdown", _H2))
        rows = [["Category", "Revenue", "Expenses", "Stock value"]]
        for row in category_breakdown[:20]:
            rows.append(
                [
                    safe_str(row.get("category_name")), format_money(row.get("revenue")),
                    format_money(row.get("expenses")), format_money(row.get("stock_value")),
                ]
            )
        story.append(_table(rows))

    # Findings & Recommendations
    findings = safe_get(payload, "findings", "recommendations", default=[])
    if findings:
        story.append(Paragraph("Recommendations", _H2))
        for rec in findings[:15]:
            story.append(Paragraph(f"• {safe_str(rec.get('title'))}: {safe_str(rec.get('description'))}", _BODY))

    # Workshop Performance (bicycle-shop template only — omitted, not
    # faked, when the underlying section is null, same PR-8.3 rule the
    # report payload itself already follows).
    workshop = payload.get("workshop_performance")
    if workshop:
        margin = workshop.get("margin") or {}
        story.append(Paragraph("Workshop Performance", _H2))
        story.append(
            Paragraph(
                f"Repairs: {safe_str(margin.get('repair_count'))} · "
                f"Revenue: {format_money((workshop.get('revenue') or {}).get('current'))} · "
                f"Margin: {format_pct(margin.get('net_gross_margin_pct') or margin.get('gross_margin_pct'))}",
                _BODY,
            )
        )

    # Forecast (aggregate figures only — the day-by-day curve is chart-
    # only data, same "chart data doesn't belong in a text/table export"
    # judgment already made for the AI chat context, app/ai/service.py's
    # own _trim_forecast_result).
    forecast_revenue = safe_get(payload, "forecast", "revenue", "result", default={})
    if forecast_revenue and not forecast_revenue.get("insufficient_data"):
        story.append(Paragraph("Revenue Forecast", _H2))
        story.append(
            Paragraph(
                f"Projected: {format_money(forecast_revenue.get('total_point'))} "
                f"(range {format_money(forecast_revenue.get('total_low'))} – "
                f"{format_money(forecast_revenue.get('total_high'))})",
                _BODY,
            )
        )

    doc.build(story)
    return buffer.getvalue()
