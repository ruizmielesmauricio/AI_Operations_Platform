"""Findings & Recommendations engine (PR-4). Pure — every rule here takes
the C9 result types (app/analytics/financial.py, app/analytics/retail.py)
and returns Findings; recommendations are then mapped from a fixed,
approved library. No DB, no I/O, no AI — see CLAUDE.md's "Business Logic
First" and PR-4.1's "reproducible; rule version recorded".

evaluate_low_stock is written to be independently callable with just a
stock-cover list and a threshold, deliberately — Stage C12 (real-time
low-stock alerts, PD-009/PR-9) will call this exact function from an
inventory-change trigger instead of re-deriving the threshold logic; the
only difference at that point is what feeds it (a fresh per-event
computation with a per-business/product configured threshold, once that
config exists) and what happens to the result (persisted as an Alert row
instead of returned in a dashboard payload).
"""

from dataclasses import dataclass
from decimal import Decimal

# Deliberately typed against the narrow, pure result types from
# financial.py/retail.py — not the assembled FinancialPerformanceSummary/
# RetailOperationsSummary dataclasses (those live in app/application/ and
# carry a MetricPeriod plus are the return type of DB-touching orchestration
# functions). Depending on them here would pull an application-layer type
# into the pure analytics layer, inverting CLAUDE.md's "logic in domain/ or
# analytics/" layering. app/application/findings.py unpacks the summaries'
# fields before calling in.
from app.analytics.financial import GrossMarginResult, ProductMarginRow, ReturnsSummary, RevenueTrend
from app.analytics.retail import DeadStockEntry, StockCoverRow

# Bumped whenever a rule's trigger condition or evidence shape changes, so a
# stored/logged finding can always be traced back to the logic that
# produced it (PR-4.1).
RULE_VERSION = 1

DEFAULT_LOW_STOCK_THRESHOLD_DAYS = Decimal("7")
_REVENUE_DECLINE_THRESHOLD_PCT = Decimal("-10")
_LOW_MARGIN_THRESHOLD_PCT = Decimal("20")
_INCOMPLETE_COST_DATA_THRESHOLD_PCT = Decimal("50")
_HIGH_RETURN_RATE_THRESHOLD_PCT = Decimal("10")
# How many of the top-revenue products to examine for evaluate_thin_
# margin_high_revenue, and how far below the business's own overall
# margin (in percentage points) counts as "meaningfully thin" rather
# than ordinary product-to-product variation. 5 mirrors the same top_n
# default rank_products_by_margin already uses everywhere else; 10
# points is a real, explainable gap — not a rounding-noise difference.
_THIN_MARGIN_TOP_N = 5
_THIN_MARGIN_GAP_PCT = Decimal("10")

Severity = str  # "critical" | "warning" | "info"
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Finding:
    type: str
    severity: Severity
    message: str
    evidence: dict
    rule_id: str
    rule_version: int = RULE_VERSION


@dataclass(frozen=True)
class RecommendationTemplate:
    title: str
    description: str


# The approved action library (PR-4.2) — every finding type maps to exactly
# one recommendation template here. A recommendation can never exist
# without a finding that triggered it, because build_recommendations only
# ever looks entries up by a finding's own type.
RECOMMENDATION_LIBRARY: dict[str, RecommendationTemplate] = {
    "revenue_decline": RecommendationTemplate(
        title="Investigate the revenue drop",
        description="Revenue fell compared to the previous period of equal length. Check for stock-outs, "
        "a slow week, or a change in footfall/marketing before assuming it's a trend.",
    ),
    "low_gross_margin": RecommendationTemplate(
        title="Review pricing or supplier costs",
        description="Overall gross margin is thin for the period. Consider whether prices need adjusting "
        "or supplier costs have crept up.",
    ),
    "incomplete_cost_data": RecommendationTemplate(
        title="Add cost prices to more products",
        description="Margin figures are based on a minority of this period's revenue because most sale "
        "line items have no recorded cost price. Add cost prices to get an accurate margin picture.",
    ),
    "product_selling_at_loss": RecommendationTemplate(
        title="Review pricing for this product",
        description="This product sold at a net loss over the period — its sale price is below its "
        "recorded cost.",
    ),
    "high_revenue_thin_margin": RecommendationTemplate(
        title="Review pricing on this top seller",
        description="This product sells well but its margin is well below your overall average — strong "
        "revenue alone doesn't mean it's healthy for profitability. Consider a price or supplier-cost review.",
    ),
    "low_stock": RecommendationTemplate(
        title="Reorder soon",
        description="At the recent sales rate, this product is projected to run out shortly.",
    ),
    "dead_stock": RecommendationTemplate(
        title="Consider a markdown or return to supplier",
        description="This product has stock on hand but hasn't sold at all in the period — cash is tied "
        "up in stock that isn't moving.",
    ),
    "high_return_rate": RecommendationTemplate(
        title="Investigate why customers are returning items",
        description="A larger-than-usual share of this period's gross revenue was refunded. Check for a "
        "product quality issue, a sizing/description mismatch, or a specific batch/supplier.",
    ),
    # Not from evaluate_all's own C9/C10-fed pipeline — built separately by
    # app/application/weather_insights.py (deterministic weather-pattern
    # sales comparison, not ML — see docs/governance/11_Development_
    # Roadmap.md v1.80) and appended to the list app/application/
    # findings.py::get_findings already builds, before recommendations are
    # built here. Kept in this same library rather than a second one so it
    # flows through the identical severity-ranking/impact-scoring machinery
    # as every other finding.
    "weather_pattern_insight": RecommendationTemplate(
        title="Consider this category's weather-linked demand pattern",
        description="Historically, sales in this category have differed meaningfully during conditions like "
        "the ones forecast for the coming week — a real pattern from your own sales history, not a "
        "prediction. Worth a look when planning stock for the week ahead.",
    ),
}


@dataclass(frozen=True)
class Recommendation:
    finding_type: str
    severity: Severity
    title: str
    description: str
    evidence: dict
    # Dollar-denominated where available (revenue at risk, loss amount,
    # uncovered revenue); a documented count-based proxy otherwise
    # (dead-stock units when cost is unknown). Only meaningful for ranking
    # within the same finding_type or severity tier, not across dollars vs.
    # unit counts.
    impact_score: Decimal


def evaluate_revenue_decline(revenue: RevenueTrend) -> list[Finding]:
    change_pct = revenue.change_pct
    if change_pct is None or change_pct > _REVENUE_DECLINE_THRESHOLD_PCT:
        return []
    return [
        Finding(
            type="revenue_decline",
            severity="warning",
            message=f"Revenue was {revenue.current} this period, down {abs(change_pct)}% "
            f"from {revenue.previous} the period before.",
            evidence={
                "current": revenue.current,
                "previous": revenue.previous,
                "change_pct": change_pct,
            },
            rule_id="revenue_decline",
        )
    ]


def evaluate_low_gross_margin(gross_margin: GrossMarginResult) -> list[Finding]:
    margin_pct = gross_margin.gross_margin_pct
    if margin_pct is None or margin_pct >= _LOW_MARGIN_THRESHOLD_PCT:
        return []
    return [
        Finding(
            type="low_gross_margin",
            severity="warning",
            message=f"Gross margin was {margin_pct}% this period, below the {_LOW_MARGIN_THRESHOLD_PCT}% watch line.",
            evidence={
                "gross_margin_pct": margin_pct,
                "gross_profit": gross_margin.gross_profit,
                "revenue_with_known_cost": gross_margin.revenue_with_known_cost,
            },
            rule_id="low_gross_margin",
        )
    ]


def evaluate_incomplete_cost_data(gross_margin: GrossMarginResult) -> list[Finding]:
    coverage_pct = gross_margin.cost_data_coverage_pct
    if coverage_pct is None or coverage_pct >= _INCOMPLETE_COST_DATA_THRESHOLD_PCT:
        return []
    return [
        Finding(
            type="incomplete_cost_data",
            severity="info",
            message=f"Only {coverage_pct}% of this period's revenue has a recorded cost price — margin "
            f"figures are based on a minority of sales.",
            evidence={
                "cost_data_coverage_pct": coverage_pct,
                "revenue_with_known_cost": gross_margin.revenue_with_known_cost,
                "total_revenue": gross_margin.total_revenue,
            },
            rule_id="incomplete_cost_data",
        )
    ]


def evaluate_high_return_rate(returns: ReturnsSummary) -> list[Finding]:
    rate_pct = returns.return_rate_pct
    if rate_pct is None or rate_pct < _HIGH_RETURN_RATE_THRESHOLD_PCT:
        return []
    return [
        Finding(
            type="high_return_rate",
            severity="warning",
            message=f"{rate_pct}% of gross revenue was refunded this period "
            f"({returns.return_count} return(s) totaling {returns.returns_amount}).",
            evidence={
                "return_rate_pct": rate_pct,
                "returns_amount": returns.returns_amount,
                "return_count": returns.return_count,
                "gross_revenue": returns.gross_revenue,
            },
            rule_id="high_return_rate",
        )
    ]


def evaluate_products_at_loss(margin_products: list[ProductMarginRow]) -> list[Finding]:
    """Pass the union of top_margin_products + bottom_margin_products
    (rank_products_by_margin's two lists), not bottom_margin_products
    alone — rank_products_by_margin deliberately leaves bottom empty
    whenever there are too few products to avoid re-listing the same rows
    in both lists, which means a loss-making product with few peers can
    end up sitting only in `top` (still the "highest" gross profit, just
    negative). Scanning both catches it either way; a loss-maker outside
    both lists only happens when there are more than top_n other products
    doing even worse, which mirrors the same top-N/bottom-N trade-off C9
    already made for the dashboard.
    """
    findings = []
    for row in margin_products:
        if row.gross_profit >= 0:
            continue
        findings.append(
            Finding(
                type="product_selling_at_loss",
                severity="warning",
                message=f"{row.name} sold at a net loss of {abs(row.gross_profit)} this period.",
                evidence={
                    "product_id": str(row.product_id),
                    "name": row.name,
                    "revenue": row.revenue,
                    "gross_profit": row.gross_profit,
                    "gross_margin_pct": row.gross_margin_pct,
                    "category_name": row.category_name,
                },
                rule_id="product_selling_at_loss",
            )
        )
    return findings


def evaluate_thin_margin_high_revenue(
    all_margin_products: list[ProductMarginRow], business_gross_margin_pct: Decimal | None
) -> list[Finding]:
    """A distinct, real question from "sold at a net loss"
    (evaluate_products_at_loss): a product can be genuinely profitable
    (gross_profit >= 0) and still be quietly dragging down overall
    profitability if it sells in volume at a much thinner margin than the
    rest of the business — "hurting profitability despite selling well."
    Live-verified real gap: rank_products_by_margin's top_n/bottom_n
    slices are ranked by gross profit, so a strong-revenue, thin-but-
    positive-margin product can rank outside both windows entirely and
    never reach evaluate_products_at_loss at all — this rule re-ranks by
    revenue instead, over the full unsliced list, specifically to find
    that product.

    No baseline to compare against without a real business-wide margin
    figure — returns [] rather than guessing when business_gross_margin_
    pct is None (no cost data at all), matching this file's established
    completeness-flag philosophy. Skips anything already caught by
    evaluate_products_at_loss (gross_profit < 0) to avoid double-flagging
    the same product under two different findings.
    """
    if business_gross_margin_pct is None:
        return []
    top_sellers_by_revenue = sorted(all_margin_products, key=lambda row: row.revenue, reverse=True)[
        :_THIN_MARGIN_TOP_N
    ]
    findings = []
    for row in top_sellers_by_revenue:
        if row.gross_profit < 0:
            continue
        if row.gross_margin_pct > business_gross_margin_pct - _THIN_MARGIN_GAP_PCT:
            continue
        findings.append(
            Finding(
                type="high_revenue_thin_margin",
                severity="warning",
                message=f"{row.name} is one of your top sellers by revenue ({row.revenue}) but its "
                f"{row.gross_margin_pct}% margin is well below your {business_gross_margin_pct}% overall "
                f"average — it may be dragging down profitability despite strong sales.",
                evidence={
                    "product_id": str(row.product_id),
                    "name": row.name,
                    "revenue": row.revenue,
                    "gross_profit": row.gross_profit,
                    "gross_margin_pct": row.gross_margin_pct,
                    "business_gross_margin_pct": business_gross_margin_pct,
                    "category_name": row.category_name,
                },
                rule_id="high_revenue_thin_margin",
            )
        )
    return findings


def resolve_low_stock_threshold(
    product_threshold: Decimal | None,
    category_threshold: Decimal | None,
) -> Decimal:
    """Product-level override wins; falls back to the category-level
    override, then to the global default (PR-9.3 — "let the owner
    configure the threshold per product or category; default provided if
    unset"). Kept next to evaluate_low_stock rather than in
    app/application/alerts.py, since it's the same deterministic-rule
    layer (no DB, no I/O) — Stage C12 just looks the two values up and
    passes them in.
    """
    if product_threshold is not None:
        return product_threshold
    if category_threshold is not None:
        return category_threshold
    return DEFAULT_LOW_STOCK_THRESHOLD_DAYS


def evaluate_low_stock(
    stock_cover: list[StockCoverRow],
    *,
    threshold_days: Decimal = DEFAULT_LOW_STOCK_THRESHOLD_DAYS,
) -> list[Finding]:
    """Standalone by design (see module docstring) — Stage C12 imports this
    function directly rather than re-deriving the threshold comparison.

    cover_days of None (no recent sales to project a depletion rate from)
    never triggers this rule — that's a dead-stock signal, not a low-stock
    one; the two rules are deliberately mutually exclusive.
    """
    findings = []
    for row in stock_cover:
        if row.cover_days is None or row.cover_days > threshold_days:
            continue
        severity = "critical" if row.cover_days == 0 else "warning"
        message = (
            f"{row.name} is out of stock."
            if row.cover_days == 0
            else f"{row.name} has about {row.cover_days} days of stock left at the recent sales rate."
        )
        findings.append(
            Finding(
                type="low_stock",
                severity=severity,
                message=message,
                evidence={
                    "product_id": str(row.product_id),
                    "name": row.name,
                    "stock_on_hand": row.stock_on_hand,
                    "cover_days": row.cover_days,
                    "revenue_in_period": row.revenue_in_period,
                    "threshold_days": threshold_days,
                    "category_name": row.category_name,
                },
                rule_id="low_stock",
            )
        )
    return findings


def evaluate_dead_stock(dead_stock: list[DeadStockEntry]) -> list[Finding]:
    findings = []
    for entry in dead_stock:
        findings.append(
            Finding(
                type="dead_stock",
                severity="info",
                message=f"{entry.name} has {entry.stock_on_hand} units on hand with no sales this period.",
                evidence={
                    "product_id": str(entry.product_id),
                    "name": entry.name,
                    "stock_on_hand": entry.stock_on_hand,
                    "value_at_cost": entry.value_at_cost,
                    "category_name": entry.category_name,
                },
                rule_id="dead_stock",
            )
        )
    return findings


def evaluate_all(
    *,
    revenue: RevenueTrend,
    gross_margin: GrossMarginResult,
    top_margin_products: list[ProductMarginRow],
    bottom_margin_products: list[ProductMarginRow],
    all_margin_products: list[ProductMarginRow],
    stock_cover: list[StockCoverRow],
    dead_stock: list[DeadStockEntry],
    returns: ReturnsSummary,
) -> list[Finding]:
    return [
        *evaluate_revenue_decline(revenue),
        *evaluate_low_gross_margin(gross_margin),
        *evaluate_incomplete_cost_data(gross_margin),
        *evaluate_products_at_loss(top_margin_products + bottom_margin_products),
        *evaluate_thin_margin_high_revenue(all_margin_products, gross_margin.gross_margin_pct),
        *evaluate_low_stock(stock_cover),
        *evaluate_dead_stock(dead_stock),
        *evaluate_high_return_rate(returns),
    ]


def _impact_score(finding: Finding) -> Decimal:
    evidence = finding.evidence
    if finding.type == "revenue_decline":
        return abs(evidence["current"] - evidence["previous"])
    if finding.type == "low_gross_margin":
        # How far below the watch line, in margin points, scaled onto the
        # revenue it applies to — a 5-point gap on ten times the revenue
        # matters more than the same gap on a trickle of sales.
        gap_pct = _LOW_MARGIN_THRESHOLD_PCT - evidence["gross_margin_pct"]
        return (gap_pct / 100) * evidence["revenue_with_known_cost"]
    if finding.type == "incomplete_cost_data":
        return evidence["total_revenue"] - evidence["revenue_with_known_cost"]
    if finding.type == "product_selling_at_loss":
        return abs(evidence["gross_profit"])
    if finding.type == "high_revenue_thin_margin":
        # Same dollar-weighted-gap shape as low_gross_margin's own score,
        # applied at the single-product level: how far below the
        # business's overall margin this product sits, scaled onto the
        # revenue it applies to.
        gap_pct = evidence["business_gross_margin_pct"] - evidence["gross_margin_pct"]
        return (gap_pct / 100) * evidence["revenue"]
    if finding.type == "low_stock":
        return evidence["revenue_in_period"]
    if finding.type == "dead_stock":
        value_at_cost = evidence["value_at_cost"]
        # Fallback proxy when cost is unknown, documented on DeadStockEntry
        # itself — count-based, not comparable across dollar-based scores.
        return value_at_cost if value_at_cost is not None else Decimal(evidence["stock_on_hand"])
    if finding.type == "high_return_rate":
        return evidence["returns_amount"]
    if finding.type == "weather_pattern_insight":
        # Not dollar-denominated (this finding has no revenue/cost figure
        # of its own) — a documented magnitude proxy, same convention as
        # dead_stock's own stock_on_hand fallback: only meaningful for
        # ranking within this same finding_type, not compared across
        # dollar-based scores.
        return abs(evidence["pct_difference"])
    raise ValueError(f"No impact scoring rule for finding type: {finding.type}")  # pragma: no cover


def build_recommendations(findings: list[Finding]) -> list[Recommendation]:
    recommendations = [
        Recommendation(
            finding_type=finding.type,
            severity=finding.severity,
            title=RECOMMENDATION_LIBRARY[finding.type].title,
            description=RECOMMENDATION_LIBRARY[finding.type].description,
            evidence=finding.evidence,
            impact_score=_impact_score(finding),
        )
        for finding in findings
    ]
    # Severity read from each recommendation's own finding instance, not a
    # type-keyed lookup — low_stock findings in particular can be
    # "critical" (out of stock) or "warning" (running low) within the same
    # batch, and collapsing that to one severity per type would misrank them.
    return sorted(
        recommendations,
        key=lambda rec: (_SEVERITY_RANK[rec.severity], -rec.impact_score),
    )


@dataclass(frozen=True)
class FindingsResult:
    findings: list[Finding]
    recommendations: list[Recommendation]
