import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.category_breakdown import get_category_breakdown
from app.application.financial_performance import get_financial_performance
from app.application.findings import get_findings
from app.application.forecast import get_forecast
from app.application.retail_operations import get_retail_operations
from app.application.workshop_performance import get_workshop_performance
from app.models.membership import Membership
from app.schemas.analytics import (
    CategoryBreakdownOut,
    FindingsOut,
    FinancialPerformanceOut,
    ForecastOut,
    RetailOperationsOut,
    WorkshopPerformanceOut,
)
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/analytics", tags=["analytics"])


@router.get("/financial-performance", response_model=FinancialPerformanceOut)
def financial_performance(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    category_id: uuid.UUID | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> FinancialPerformanceOut:
    summary = get_financial_performance(
        db, business_id=business_id, start_date=start, end_date=end, category_id=category_id
    )
    return FinancialPerformanceOut.model_validate(summary)


@router.get("/retail-operations", response_model=RetailOperationsOut)
def retail_operations(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    category_id: uuid.UUID | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> RetailOperationsOut:
    summary = get_retail_operations(
        db, business_id=business_id, start_date=start, end_date=end, category_id=category_id
    )
    return RetailOperationsOut.model_validate(summary)


@router.get("/category-breakdown", response_model=CategoryBreakdownOut)
def category_breakdown(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> CategoryBreakdownOut:
    summary = get_category_breakdown(db, business_id=business_id, start_date=start, end_date=end)
    return CategoryBreakdownOut.model_validate(summary)


@router.get("/workshop-performance", response_model=WorkshopPerformanceOut)
def workshop_performance(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> WorkshopPerformanceOut:
    summary = get_workshop_performance(db, business_id=business_id, start_date=start, end_date=end)
    return WorkshopPerformanceOut.model_validate(summary)


@router.get("/findings", response_model=FindingsOut)
def findings(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    category_id: uuid.UUID | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> FindingsOut:
    summary = get_findings(db, business_id=business_id, start_date=start, end_date=end, category_id=category_id)
    return FindingsOut.model_validate(summary)


@router.get("/forecast", response_model=ForecastOut)
def forecast(
    business_id: uuid.UUID,
    horizon_days: int = Query(7, ge=1, le=90),
    category_id: uuid.UUID | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ForecastOut:
    # Not period-scoped like the four routes above (start/end) — a forecast
    # is always forward-looking from "today" in the business's own
    # timezone; horizon_days controls how far ahead, not which historical
    # window to read (that's the lookback window inside get_forecast).
    # category_id only scopes the per-product table — see get_forecast's
    # own comment on why the revenue forecast figure stays whole-business.
    summary = get_forecast(db, business_id=business_id, horizon_days=horizon_days, category_id=category_id)
    return ForecastOut.model_validate(summary)
