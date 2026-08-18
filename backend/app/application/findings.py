"""Orchestrates the Findings & Recommendations summary for a route: runs
the existing C9 application functions for the period, then feeds their
results into the pure rules in app/analytics/findings.py. No calculation
logic of its own — see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.analytics.findings import Finding, Recommendation, build_recommendations, evaluate_all
from app.analytics.period import MetricPeriod
from app.application.financial_performance import get_financial_performance
from app.application.retail_operations import get_retail_operations
from app.application.weather_insights import get_weather_pattern_findings
from app.models.business import Business


@dataclass(frozen=True)
class FindingsSummary:
    period: MetricPeriod
    findings: list[Finding]
    recommendations: list[Recommendation]


def get_findings(
    db: Session,
    *,
    business_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    category_id: uuid.UUID | None = None,
) -> FindingsSummary:
    # Both calls resolve the period independently from the same
    # (business_id, start_date, end_date) inputs — resolve_period is a pure
    # function of those inputs (app/analytics/period.py), so the two
    # resulting periods are always identical; no risk of the financial and
    # retail findings being evaluated against different windows.
    financial = get_financial_performance(db, business_id=business_id, start_date=start_date, end_date=end_date)
    retail = get_retail_operations(db, business_id=business_id, start_date=start_date, end_date=end_date)

    # Per-product rules (products_at_loss/low_stock/dead_stock) get a
    # second, category-filtered pair of calls when a filter is active —
    # never the whole-business rules (revenue_decline/low_gross_margin/
    # incomplete_cost_data/high_return_rate), per direct instruction: a
    # revenue-decline finding is a whole-business trend, not something
    # that should silently change meaning depending on a stock filter.
    # Only category_id differs between the two calls, so this is one
    # extra pair of (already-existing) queries, not new query logic.
    product_financial = financial
    product_retail = retail
    if category_id is not None:
        product_financial = get_financial_performance(
            db, business_id=business_id, start_date=start_date, end_date=end_date, category_id=category_id
        )
        product_retail = get_retail_operations(
            db, business_id=business_id, start_date=start_date, end_date=end_date, category_id=category_id
        )

    findings = evaluate_all(
        revenue=financial.revenue,
        gross_margin=financial.gross_margin,
        top_margin_products=product_financial.top_margin_products,
        bottom_margin_products=product_financial.bottom_margin_products,
        all_margin_products=product_financial.all_margin_products,
        stock_cover=product_retail.stock_cover,
        dead_stock=product_retail.dead_stock,
        returns=financial.returns,
    )

    # Deterministic weather-pattern insight (app/application/
    # weather_insights.py) — not part of evaluate_all's own C9/C10-fed
    # pipeline, since it reads a different data source (this business's
    # own accumulated weather_observations + a live forecast call) and
    # not just already-computed financial/retail summaries. Always []
    # when a category filter is active (category_id is not None) — this
    # finding already names its own specific category per comparison, so
    # filtering it down further doesn't map onto any existing per-product
    # filter shape the way stock/margin findings do. Never lets a
    # weather-provider hiccup break the rest of Findings & Recommendations
    # — get_weather_pattern_findings itself never raises.
    if category_id is None:
        business = db.get(Business, business_id)
        if business is not None:
            findings = findings + get_weather_pattern_findings(db, business=business)

    recommendations = build_recommendations(findings)

    return FindingsSummary(period=financial.period, findings=findings, recommendations=recommendations)
