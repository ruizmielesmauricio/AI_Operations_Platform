"""Complete PDF rendering for stored weekly and monthly reports.

The exporter formats the already-computed ``Report.payload`` only. It does
not recalculate analytics. Its section coverage mirrors the report detail
page, including the data behind each web chart.
"""

from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from html import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.exports.formatting import format_money, format_pct, format_rate, safe_get, safe_str

_PAGE_WIDTH, _PAGE_HEIGHT = A4
_CONTENT_WIDTH = _PAGE_WIDTH - 3 * cm
_INK = colors.HexColor("#17212b")
_MUTED = colors.HexColor("#5f6b76")
_TEAL = colors.HexColor("#0f766e")
_BLUE = colors.HexColor("#2563eb")
_AMBER = colors.HexColor("#d97706")
_RED = colors.HexColor("#c2410c")
_PALE = colors.HexColor("#f4f6f8")
_BORDER = colors.HexColor("#d7dde2")

_STYLES = getSampleStyleSheet()
_H1 = ParagraphStyle(
    "ORLAH1", parent=_STYLES["Heading1"], fontName="Helvetica-Bold", fontSize=20,
    leading=24, textColor=_INK, spaceAfter=8,
)
_H2 = ParagraphStyle(
    "ORLAH2", parent=_STYLES["Heading2"], fontName="Helvetica-Bold", fontSize=14,
    leading=17, textColor=_INK, spaceBefore=15, spaceAfter=7, keepWithNext=True,
)
_H3 = ParagraphStyle(
    "ORLAH3", parent=_STYLES["Heading3"], fontName="Helvetica-Bold", fontSize=10.5,
    leading=13, textColor=_TEAL, spaceBefore=9, spaceAfter=5, keepWithNext=True,
)
_BODY = ParagraphStyle(
    "ORLABody", parent=_STYLES["BodyText"], fontName="Helvetica", fontSize=9,
    leading=12, textColor=_INK, spaceAfter=4,
)
_SMALL = ParagraphStyle(
    "ORLASmall", parent=_BODY, fontSize=7.5, leading=9.5, textColor=_MUTED,
)
_TABLE_HEADER = ParagraphStyle(
    "ORLATableHeader", parent=_SMALL, fontName="Helvetica-Bold", textColor=colors.white,
    alignment=TA_LEFT,
)
_TABLE_CELL = ParagraphStyle("ORLATableCell", parent=_SMALL, textColor=_INK)
_TABLE_CELL_RIGHT = ParagraphStyle("ORLATableCellRight", parent=_TABLE_CELL, alignment=2)
_CALLOUT = ParagraphStyle(
    "ORLACallout", parent=_BODY, leftIndent=8, borderColor=_BORDER, borderWidth=0.5,
    borderPadding=7, backColor=_PALE, spaceBefore=3, spaceAfter=7,
)

_BUSINESS_WIDE_FINDING_TYPES = {
    "revenue_decline",
    "low_gross_margin",
    "incomplete_cost_data",
    "high_return_rate",
}


def _text(value: object, default: str = "-") -> str:
    return escape(safe_str(value, default))


def _paragraph(value: object, style: ParagraphStyle = _TABLE_CELL) -> Paragraph:
    return Paragraph(_text(value), style)


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _table(
    headers: list[str],
    rows: list[list[object]],
    *,
    col_widths: list[float] | None = None,
    right_align: set[int] | None = None,
) -> Table:
    right_align = right_align or set()
    rendered: list[list[Paragraph]] = [
        [_paragraph(header, _TABLE_HEADER) for header in headers]
    ]
    for row in rows:
        rendered.append(
            [
                _paragraph(value, _TABLE_CELL_RIGHT if index in right_align else _TABLE_CELL)
                for index, value in enumerate(row)
            ]
        )
    table = Table(rendered, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _INK),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _PALE]),
                ("GRID", (0, 0), (-1, -1), 0.4, _BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _metric_table(rows: list[tuple[str, str]]) -> Table:
    return _table(
        ["Metric", "Value"],
        [[label, value] for label, value in rows],
        col_widths=[_CONTENT_WIDTH * 0.58, _CONTENT_WIDTH * 0.42],
        right_align={1},
    )


def _bar_chart(
    rows: list[dict],
    *,
    label_key: str,
    value_key: str,
    title: str,
    color: colors.Color = _TEAL,
    max_items: int = 12,
) -> Drawing | None:
    values: list[tuple[str, float]] = []
    for row in rows:
        value = _number(row.get(value_key))
        if value is not None:
            values.append((safe_str(row.get(label_key), "Uncategorized"), value))
    if not values:
        return None

    values = values[:max_items]
    drawing = Drawing(_CONTENT_WIDTH, 220)
    drawing.add(String(0, 204, title, fontName="Helvetica-Bold", fontSize=9, fillColor=_INK))
    chart = VerticalBarChart()
    chart.x = 48
    chart.y = 44
    chart.width = _CONTENT_WIDTH - 62
    chart.height = 140
    chart.data = [[value for _, value in values]]
    chart.categoryAxis.categoryNames = [label[:20] for label, _ in values]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 6.5
    chart.categoryAxis.labels.angle = 30
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.categoryAxis.labels.dy = -4
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = min(0, min(value for _, value in values))
    chart.valueAxis.valueMax = max(1, max(value for _, value in values))
    chart.valueAxis.gridStrokeColor = _BORDER
    chart.valueAxis.gridStrokeWidth = 0.4
    chart.bars[0].fillColor = color
    chart.bars[0].strokeColor = color
    chart.barWidth = 12
    drawing.add(chart)
    return drawing


def _forecast_chart(daily: list[dict]) -> Drawing | None:
    points: list[tuple[str, float, float, float]] = []
    for row in daily:
        point = _number(row.get("point"))
        low = _number(row.get("low"))
        high = _number(row.get("high"))
        if point is not None and low is not None and high is not None:
            points.append((safe_str(row.get("forecast_date")), point, low, high))
    if not points:
        return None

    drawing = Drawing(_CONTENT_WIDTH, 230)
    drawing.add(String(0, 214, "Daily revenue forecast", fontName="Helvetica-Bold", fontSize=9, fillColor=_INK))
    chart = HorizontalLineChart()
    chart.x = 48
    chart.y = 50
    chart.width = _CONTENT_WIDTH - 62
    chart.height = 140
    chart.data = [
        [point for _, point, _, _ in points],
        [low for _, _, low, _ in points],
        [high for _, _, _, high in points],
    ]
    label_every = max(1, len(points) // 8)
    chart.categoryAxis.categoryNames = [
        label[-5:] if index % label_every == 0 or index == len(points) - 1 else ""
        for index, (label, _, _, _) in enumerate(points)
    ]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.gridStrokeColor = _BORDER
    chart.valueAxis.gridStrokeWidth = 0.4
    chart.lines[0].strokeColor = _BLUE
    chart.lines[0].strokeWidth = 2
    chart.lines[1].strokeColor = _AMBER
    chart.lines[1].strokeWidth = 1
    chart.lines[2].strokeColor = _TEAL
    chart.lines[2].strokeWidth = 1
    drawing.add(chart)

    for x, color, label in (
        (48, _BLUE, "Expected"),
        (135, _AMBER, "Low"),
        (190, _TEAL, "High"),
    ):
        drawing.add(Rect(x, 18, 12, 3, strokeColor=color, fillColor=color))
        drawing.add(String(x + 16, 15, label, fontName="Helvetica", fontSize=7, fillColor=_INK))
    return drawing


def _product_name(row: dict) -> str:
    name = safe_str(row.get("name"))
    category = row.get("category_name")
    return f"{name} - {category}" if category else name


def _recommendation_blocks(recommendations: list[dict], findings: list[dict]) -> list[Paragraph]:
    finding_by_key = {
        (finding.get("type"), (finding.get("evidence") or {}).get("product_id")): finding
        for finding in findings
    }
    blocks: list[Paragraph] = []
    for recommendation in recommendations:
        evidence = recommendation.get("evidence") or {}
        finding = finding_by_key.get((recommendation.get("finding_type"), evidence.get("product_id")))
        category = evidence.get("category_name")
        title = safe_str(recommendation.get("title"))
        if category:
            title = f"{title} - {category}"
        message = f" - {safe_str(finding.get('message'))}" if finding else ""
        description = safe_str(recommendation.get("description"), "")
        severity = safe_str(recommendation.get("severity"), "info").upper()
        blocks.append(Paragraph(f"<b>{escape(severity)}: {escape(title)}</b>{escape(message)}<br/>{escape(description)}", _CALLOUT))
    return blocks


def _page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, _PAGE_WIDTH, _PAGE_HEIGHT, stroke=0, fill=1)
    canvas.setStrokeColor(_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(1.5 * cm, 1.15 * cm, _PAGE_WIDTH - 1.5 * cm, 1.15 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(_MUTED)
    canvas.drawString(1.5 * cm, 0.75 * cm, "ORLA report - deterministic business analytics")
    canvas.drawRightString(_PAGE_WIDTH - 1.5 * cm, 0.75 * cm, f"Page {doc.page}")
    canvas.restoreState()


def render_report_pdf(payload: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1.35 * cm,
        bottomMargin=1.55 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        title=f"{safe_str(payload.get('business_name'))} report",
        author="ORLA",
    )
    story: list = []

    label = "Weekly" if payload.get("report_type") == "weekly" else "Monthly"
    story.append(Paragraph(f"{_text(payload.get('business_name'))} - {label} Report", _H1))
    story.append(Paragraph(
        f"{_text(payload.get('period_start'))} to {_text(payload.get('period_end'))} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Generated {_text(payload.get('generated_at'))}", _SMALL,
    ))
    story.append(Spacer(1, 0.12 * cm))
    story.append(Paragraph(
        "Every figure in this export comes from the same deterministic calculations used by the ORLA report page.",
        _CALLOUT,
    ))

    summary = safe_get(payload, "executive_summary", default={})
    financial = safe_get(payload, "financial_performance", default={})
    retail = safe_get(payload, "retail_operations", default={})
    inventory = safe_get(payload, "inventory_health", default={})
    forecast = safe_get(payload, "forecast", default={})
    findings_section = safe_get(payload, "findings", default={})
    all_findings = findings_section.get("findings") or []
    all_recommendations = findings_section.get("recommendations") or []

    story.append(Paragraph("Executive Summary", _H2))
    for line in summary.get("narrative") or []:
        story.append(Paragraph(f"- {_text(line)}", _BODY))
    gross_margin = financial.get("gross_margin") or {}
    preferred_margin_pct = gross_margin.get("net_gross_margin_pct") or gross_margin.get("gross_margin_pct")
    story.append(_metric_table([
        ("Revenue", format_money(safe_get(financial, "revenue", "current"))),
        ("Transactions", safe_str(summary.get("transactions"))),
        ("Average sale", format_money(summary.get("average_sale"))),
        ("Gross margin", format_pct(preferred_margin_pct)),
        ("Inventory value at cost", format_money(safe_get(retail, "inventory_value", "value_at_cost"))),
        ("Low stock products", safe_str(summary.get("low_stock_count"))),
        ("Dead stock products", safe_str(summary.get("dead_stock_count"))),
    ]))
    top_recommendations = summary.get("top_recommendations") or []
    if top_recommendations:
        story.append(Paragraph("Top recommendations", _H3))
        story.extend(_recommendation_blocks(top_recommendations, all_findings))

    story.append(Paragraph("Revenue Performance", _H2))
    revenue = financial.get("revenue") or {}
    trend_name = "last week" if payload.get("report_type") == "weekly" else "last month"
    story.append(_metric_table([
        ("Revenue", format_money(revenue.get("current"))),
        (f"Revenue - {trend_name}", format_money(revenue.get("previous"))),
        (f"Change vs {trend_name}", format_pct(revenue.get("change_pct"))),
        ("Gross profit", format_money(gross_margin.get("net_gross_profit") or gross_margin.get("gross_profit"))),
        ("Gross margin", format_pct(preferred_margin_pct)),
        ("Cost data coverage", format_pct(gross_margin.get("cost_data_coverage_pct"))),
        ("Tax data coverage", format_pct(gross_margin.get("tax_data_coverage_pct"))),
    ]))
    returns = financial.get("returns") or {}
    if _number(returns.get("returns_amount")) not in (None, 0):
        story.append(Paragraph("Returns", _H3))
        story.append(_metric_table([
            ("Gross revenue before returns", format_money(returns.get("gross_revenue"))),
            ("Returns", f"{safe_str(returns.get('return_count'))} / {format_money(returns.get('returns_amount'))}"),
            ("Return rate", format_pct(returns.get("return_rate_pct"))),
            ("Net revenue", format_money(returns.get("net_revenue"))),
        ]))

    margin_rows_by_id = {}
    for row in [*(financial.get("bottom_margin_products") or []), *(financial.get("top_margin_products") or [])]:
        margin_rows_by_id[row.get("product_id") or row.get("name")] = row
    margin_rows = list(margin_rows_by_id.values())
    margin_chart = _bar_chart(
        margin_rows, label_key="name", value_key="gross_profit", title="Gross profit by product (EUR)", color=_BLUE,
    )
    if margin_chart:
        story.append(Spacer(1, 0.15 * cm))
        story.append(margin_chart)
        story.append(_table(
            ["Product", "Revenue", "Gross profit", "Margin"],
            [[_product_name(row), format_money(row.get("revenue")), format_money(row.get("gross_profit")), format_pct(row.get("gross_margin_pct"))] for row in margin_rows],
            col_widths=[_CONTENT_WIDTH * 0.43, _CONTENT_WIDTH * 0.19, _CONTENT_WIDTH * 0.21, _CONTENT_WIDTH * 0.17],
            right_align={1, 2, 3},
        ))
    excluded_margin = financial.get("products_excluded_from_ranking") or 0
    if excluded_margin:
        story.append(Paragraph(f"{_text(excluded_margin)} product(s) were excluded from margin ranking because cost data was unavailable.", _SMALL))

    story.append(Paragraph("Sales Performance", _H2))
    for heading, rows in (
        ("Top sellers by units", retail.get("top_sellers_by_units") or []),
        ("Top sellers by revenue", retail.get("top_sellers_by_revenue") or []),
    ):
        story.append(Paragraph(heading, _H3))
        if rows:
            story.append(_table(
                ["Product", "Units sold", "Revenue"],
                [[_product_name(row), row.get("units_sold"), format_money(row.get("revenue"))] for row in rows],
                col_widths=[_CONTENT_WIDTH * 0.58, _CONTENT_WIDTH * 0.19, _CONTENT_WIDTH * 0.23],
                right_align={1, 2},
            ))
        else:
            story.append(Paragraph("No sales in this period.", _BODY))

    story.append(Paragraph("Category Breakdown", _H2))
    story.append(Paragraph(
        "Expenses are purchase cost, not cost of goods sold. Stock value is shown at sell price. Products without a category are grouped as Uncategorized.",
        _SMALL,
    ))
    category_rows = safe_get(payload, "category_breakdown", "rows", default=[])
    if category_rows:
        story.append(_table(
            ["Category", "Revenue", "Expenses", "Stock value", "Data notes"],
            [
                [
                    row.get("category_name"),
                    format_money(row.get("revenue")),
                    format_money(row.get("expenses")),
                    format_money(row.get("stock_value")),
                    "; ".join(
                        note for note in [
                            (
                                f"Purchase cost coverage {format_pct(row.get('expenses_data_coverage_pct'))}"
                                if row.get("expenses_data_coverage_pct") is not None
                                and (_number(row.get("expenses_data_coverage_pct")) or 0) < 100
                                else ""
                            ),
                            (
                                f"{row.get('products_excluded_from_stock_value')} product(s) excluded - no sell price"
                                if row.get("products_excluded_from_stock_value")
                                else ""
                            ),
                        ] if note
                    ) or "-",
                ]
                for row in category_rows
            ],
            col_widths=[3.2 * cm, 2.2 * cm, 2.2 * cm, 2.4 * cm, _CONTENT_WIDTH - 10 * cm],
            right_align={1, 2, 3},
        ))
    else:
        story.append(Paragraph("No category data for this period.", _BODY))

    story.append(PageBreak())
    story.append(Paragraph("Inventory Health", _H2))
    story.append(_metric_table([
        ("Inventory value at cost", format_money(safe_get(retail, "inventory_value", "value_at_cost"))),
        ("Products missing cost", safe_str(safe_get(retail, "inventory_value", "products_missing_cost"))),
        ("Sell-through rate", format_rate(retail.get("sell_through_rate"))),
        ("Inventory turnover", f"{safe_str(inventory.get('turnover_ratio'))}x" if inventory.get("turnover_ratio") is not None else "-"),
    ]))
    stock_cover = [row for row in (retail.get("stock_cover") or []) if row.get("cover_days") is not None]
    story.append(Paragraph("Stock cover", _H3))
    cover_chart = _bar_chart(stock_cover, label_key="name", value_key="cover_days", title="Estimated days of stock cover", color=_TEAL)
    if cover_chart:
        story.append(cover_chart)
        story.append(_table(
            ["Product", "In stock", "Sold", "Cover", "Revenue"],
            [[_product_name(row), row.get("stock_on_hand"), row.get("units_sold_in_period"), f"{safe_str(row.get('cover_days'))} days", format_money(row.get("revenue_in_period"))] for row in stock_cover],
            col_widths=[_CONTENT_WIDTH * 0.42, _CONTENT_WIDTH * 0.13, _CONTENT_WIDTH * 0.12, _CONTENT_WIDTH * 0.15, _CONTENT_WIDTH * 0.18],
            right_align={1, 2, 3, 4},
        ))
    else:
        story.append(Paragraph("Not enough recent sales to estimate stock cover.", _BODY))

    for heading, explanation, rows in (
        ("Fast movers", "Products selling through quickly (14 days of cover or less).", inventory.get("fast_movers") or []),
        ("Slow movers", "Products with 60 or more days of cover.", inventory.get("slow_movers") or []),
    ):
        story.append(Paragraph(heading, _H3))
        story.append(Paragraph(explanation, _SMALL))
        if rows:
            story.append(_table(
                ["Product", "Stock on hand", "Cover left"],
                [[_product_name(row), row.get("stock_on_hand"), f"{safe_str(row.get('cover_days'))} days"] for row in rows],
                col_widths=[_CONTENT_WIDTH * 0.62, _CONTENT_WIDTH * 0.18, _CONTENT_WIDTH * 0.20],
                right_align={1, 2},
            ))
        else:
            story.append(Paragraph("None this period.", _BODY))

    dead_stock = retail.get("dead_stock") or []
    story.append(Paragraph("Dead stock", _H3))
    story.append(Paragraph("Products with stock on hand but zero sales during the report period.", _SMALL))
    if dead_stock:
        story.append(_table(
            ["Product", "Stock on hand", "Value at cost"],
            [[_product_name(row), row.get("stock_on_hand"), format_money(row.get("value_at_cost")) if row.get("value_at_cost") is not None else "Unknown"] for row in dead_stock],
            col_widths=[_CONTENT_WIDTH * 0.62, _CONTENT_WIDTH * 0.18, _CONTENT_WIDTH * 0.20],
            right_align={1, 2},
        ))
    else:
        story.append(Paragraph("None - every product with stock on hand sold at least once this period.", _BODY))

    story.append(Paragraph("Forecast & Future Outlook", _H2))
    revenue_forecast = safe_get(forecast, "revenue", "result", default={})
    if revenue_forecast.get("insufficient_data"):
        story.append(Paragraph("Not enough sales history yet to forecast revenue.", _BODY))
    else:
        horizon = forecast.get("horizon_days") or safe_get(forecast, "revenue", "horizon_days")
        story.append(_metric_table([
            (f"Expected revenue - next {safe_str(horizon)} days", format_money(revenue_forecast.get("total_point"))),
            ("Expected range", f"{format_money(revenue_forecast.get('total_low'))} to {format_money(revenue_forecast.get('total_high'))}"),
            ("Forecast method", safe_str(revenue_forecast.get("method"))),
            ("History used", f"{safe_str(revenue_forecast.get('history_days_used'))} days"),
        ]))
        daily = revenue_forecast.get("daily") or []
        forecast_chart = _forecast_chart(daily)
        if forecast_chart:
            story.append(forecast_chart)
            story.append(_table(
                ["Date", "Expected", "Low", "High"],
                [[row.get("forecast_date"), format_money(row.get("point")), format_money(row.get("low")), format_money(row.get("high"))] for row in daily],
                col_widths=[_CONTENT_WIDTH * 0.28, _CONTENT_WIDTH * 0.24, _CONTENT_WIDTH * 0.24, _CONTENT_WIDTH * 0.24],
                right_align={1, 2, 3},
            ))

    story.append(Paragraph("Purchasing Recommendations", _H2))
    product_forecasts = forecast.get("products") or []
    if product_forecasts:
        story.append(_table(
            ["Product", "Current", "Forecast demand", "Cover", "Reorder"],
            [
                [
                    _product_name(row),
                    row.get("current_stock"),
                    f"{safe_str(safe_get(row, 'result', 'total_point'))} ({safe_str(safe_get(row, 'result', 'total_low'))}-{safe_str(safe_get(row, 'result', 'total_high'))})",
                    f"{safe_str(row.get('days_of_cover_at_forecast_rate'))} days" if row.get("days_of_cover_at_forecast_rate") is not None else "-",
                    row.get("suggested_reorder_quantity") or "-",
                ]
                for row in product_forecasts
            ],
            col_widths=[_CONTENT_WIDTH * 0.38, _CONTENT_WIDTH * 0.12, _CONTENT_WIDTH * 0.25, _CONTENT_WIDTH * 0.13, _CONTENT_WIDTH * 0.12],
            right_align={1, 2, 3, 4},
        ))
        excluded_forecasts = forecast.get("products_excluded_insufficient_data") or 0
        if excluded_forecasts:
            story.append(Paragraph(f"{_text(excluded_forecasts)} product(s) were excluded because there was not enough sales history.", _SMALL))
    else:
        story.append(Paragraph("No products have enough sales history yet to forecast demand.", _BODY))

    workshop = payload.get("workshop_performance")
    if workshop:
        workshop_margin = workshop.get("margin") or {}
        workshop_revenue = workshop.get("revenue") or {}
        workshop_margin_pct = workshop_margin.get("net_gross_margin_pct") or workshop_margin.get("gross_margin_pct")
        story.append(Paragraph("Workshop Performance", _H2))
        story.append(_metric_table([
            ("Repairs completed", safe_str(workshop_margin.get("repair_count"))),
            ("Revenue", format_money(workshop_revenue.get("current"))),
            (f"Revenue - {trend_name}", format_money(workshop_revenue.get("previous"))),
            (f"Change vs {trend_name}", format_pct(workshop_revenue.get("change_pct"))),
            ("Average ticket", format_money(workshop_margin.get("average_ticket"))),
            ("Gross margin - labour only", format_pct(workshop_margin_pct)),
            ("Labour cost coverage", format_pct(workshop_margin.get("labour_cost_coverage_pct"))),
            ("Tax data coverage", format_pct(workshop_margin.get("tax_data_coverage_pct"))),
        ]))

    story.append(Paragraph("Action Plan", _H2))
    business_wide = [rec for rec in all_recommendations if rec.get("finding_type") in _BUSINESS_WIDE_FINDING_TYPES]
    stock_and_products = [rec for rec in all_recommendations if rec.get("finding_type") not in _BUSINESS_WIDE_FINDING_TYPES]
    if not business_wide and not stock_and_products:
        story.append(Paragraph("Nothing to flag for this period.", _BODY))
    else:
        if business_wide:
            story.append(Paragraph("Business performance", _H3))
            story.extend(_recommendation_blocks(business_wide, all_findings))
        if stock_and_products:
            story.append(Paragraph("Stock & products", _H3))
            story.extend(_recommendation_blocks(stock_and_products, all_findings))

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    return buffer.getvalue()
