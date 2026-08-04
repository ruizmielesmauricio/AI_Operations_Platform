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
) -> FindingsSummary:
    # Both calls resolve the period independently from the same
    # (business_id, start_date, end_date) inputs — resolve_period is a pure
    # function of those inputs (app/analytics/period.py), so the two
    # resulting periods are always identical; no risk of the financial and
    # retail findings being evaluated against different windows.
    financial = get_financial_performance(db, business_id=business_id, start_date=start_date, end_date=end_date)
    retail = get_retail_operations(db, business_id=business_id, start_date=start_date, end_date=end_date)

    findings = evaluate_all(
        revenue=financial.revenue,
        gross_margin=financial.gross_margin,
        top_margin_products=financial.top_margin_products,
        bottom_margin_products=financial.bottom_margin_products,
        stock_cover=retail.stock_cover,
        dead_stock=retail.dead_stock,
    )
    recommendations = build_recommendations(findings)

    return FindingsSummary(period=financial.period, findings=findings, recommendations=recommendations)
