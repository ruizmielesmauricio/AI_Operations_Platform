"""Workshop Performance formulas (02_Operational_Domains.md domain 2,
PR-3). Pure — same conventions as financial.py/retail.py: plain inputs,
quantized Decimal results, no DB, no I/O.

Labour-only profitability: ProductionEventInput (parts consumed per
repair) has no writer yet — the v1 repairs upload captures price_charged/
labour_cost per job but not a parts breakdown — so "cost" here means
labour cost, not full COGS. Same honesty pattern as financial.py's
cost_data_coverage_pct: the numbers are real, just partial, and the
completeness flag says so rather than the margin silently overstating.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.analytics.types import RepairPeriodTotals

_CENTS = Decimal("0.01")
_TENTH_PERCENT = Decimal("0.1")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal) -> Decimal:
    return value.quantize(_TENTH_PERCENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class WorkshopMarginResult:
    repair_count: int
    revenue: Decimal
    # repairs_with_known_price / repair_count, as a percentage — the PR-3.5
    # completeness flag for revenue itself: unlike a sale's unit_price,
    # price_charged is nullable on a repair row, so revenue can already be
    # partial before cost even enters into it.
    revenue_coverage_pct: Decimal | None
    labour_cost: Decimal
    gross_profit: Decimal
    # None when labour_cost_known_revenue is 0 — nothing to divide by.
    gross_margin_pct: Decimal | None
    # labour_cost_known_revenue / revenue, as a percentage — same role as
    # financial.py's cost_data_coverage_pct, scoped to labour cost only.
    labour_cost_coverage_pct: Decimal | None
    # None when no repair has a known price to average.
    average_ticket: Decimal | None


def compute_workshop_margin(totals: RepairPeriodTotals) -> WorkshopMarginResult:
    revenue_coverage_pct = (
        _quantize_pct(Decimal(totals.repairs_with_known_price) / totals.repair_count * 100)
        if totals.repair_count > 0
        else None
    )
    gross_profit = totals.labour_cost_known_revenue - totals.labour_cost
    gross_margin_pct = (
        _quantize_pct(gross_profit / totals.labour_cost_known_revenue * 100)
        if totals.labour_cost_known_revenue > 0
        else None
    )
    labour_cost_coverage_pct = (
        _quantize_pct(totals.labour_cost_known_revenue / totals.revenue * 100) if totals.revenue > 0 else None
    )
    average_ticket = (
        _quantize_money(totals.revenue / totals.repairs_with_known_price)
        if totals.repairs_with_known_price > 0
        else None
    )

    return WorkshopMarginResult(
        repair_count=totals.repair_count,
        revenue=_quantize_money(totals.revenue),
        revenue_coverage_pct=revenue_coverage_pct,
        labour_cost=_quantize_money(totals.labour_cost),
        gross_profit=_quantize_money(gross_profit),
        gross_margin_pct=gross_margin_pct,
        labour_cost_coverage_pct=labour_cost_coverage_pct,
        average_ticket=average_ticket,
    )
