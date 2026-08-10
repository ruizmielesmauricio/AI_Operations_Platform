import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.business_group import (
    MixedTimezoneGroup,
    NotGroupMember,
    get_financial_performance_for_group,
    get_findings_for_group,
    get_forecast_for_group,
    get_retail_operations_for_group,
    get_workshop_performance_for_group,
    resolve_authorized_group,
)
from app.application.category_breakdown import get_category_breakdown
from app.application.financial_performance import get_financial_performance
from app.application.findings import get_findings
from app.application.forecast import get_forecast
from app.application.retail_operations import get_retail_operations
from app.application.workshop_performance import get_workshop_performance
from app.models.business import Business
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

# Shared by every route below: "all_branches=true" swaps a single-business
# read for the combined view across business_id's whole standalone-shop-
# plus-branches group (direct request). Kept as one helper so each route
# only differs in which get_X_for_group function it calls, not in how the
# group gets resolved/authorized/errors get mapped.
_ALL_BRANCHES_DESCRIPTION = (
    "Combine this business with every branch in its group (or its parent "
    "and siblings, if this id is itself a branch) into one view, instead "
    "of reading this business alone."
)


def _resolve_group_or_error(db: Session, *, business_id: uuid.UUID, user_id: str) -> list[Business]:
    try:
        return resolve_authorized_group(db, business_id=business_id, user_id=user_id)
    except NotGroupMember as exc:
        # Deliberately the same 403 shape as get_current_membership's own
        # "not a member of this business" — combining data across
        # businesses the caller doesn't have access to is exactly the
        # same tenant-isolation violation as reading one directly.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of every business in this group"
        ) from exc
    except MixedTimezoneGroup as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This shop's branches don't all share one timezone "
                f"({', '.join(exc.timezones)}), so they can't be combined into one view. "
                "View each business individually instead."
            ),
        ) from exc


@router.get("/financial-performance", response_model=FinancialPerformanceOut)
def financial_performance(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    category_id: uuid.UUID | None = None,
    all_branches: bool = Query(default=False, description=_ALL_BRANCHES_DESCRIPTION),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> FinancialPerformanceOut:
    if all_branches:
        group = _resolve_group_or_error(db, business_id=business_id, user_id=membership.user_id)
        summary = get_financial_performance_for_group(
            db, businesses=group, start_date=start, end_date=end, category_id=category_id
        )
    else:
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
    all_branches: bool = Query(default=False, description=_ALL_BRANCHES_DESCRIPTION),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> RetailOperationsOut:
    if all_branches:
        group = _resolve_group_or_error(db, business_id=business_id, user_id=membership.user_id)
        summary = get_retail_operations_for_group(
            db, businesses=group, start_date=start, end_date=end, category_id=category_id
        )
    else:
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
    # Not offered in "All branches" form — deliberately out of the scope
    # confirmed for this feature (Financial/Retail/Workshop/Forecast/
    # Findings only).
    summary = get_category_breakdown(db, business_id=business_id, start_date=start, end_date=end)
    return CategoryBreakdownOut.model_validate(summary)


@router.get("/workshop-performance", response_model=WorkshopPerformanceOut)
def workshop_performance(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    all_branches: bool = Query(default=False, description=_ALL_BRANCHES_DESCRIPTION),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> WorkshopPerformanceOut:
    if all_branches:
        group = _resolve_group_or_error(db, business_id=business_id, user_id=membership.user_id)
        summary = get_workshop_performance_for_group(db, businesses=group, start_date=start, end_date=end)
    else:
        summary = get_workshop_performance(db, business_id=business_id, start_date=start, end_date=end)
    return WorkshopPerformanceOut.model_validate(summary)


@router.get("/findings", response_model=FindingsOut)
def findings(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    category_id: uuid.UUID | None = None,
    all_branches: bool = Query(default=False, description=_ALL_BRANCHES_DESCRIPTION),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> FindingsOut:
    if all_branches:
        group = _resolve_group_or_error(db, business_id=business_id, user_id=membership.user_id)
        summary = get_findings_for_group(
            db, businesses=group, start_date=start, end_date=end, category_id=category_id
        )
    else:
        summary = get_findings(db, business_id=business_id, start_date=start, end_date=end, category_id=category_id)
    return FindingsOut.model_validate(summary)


@router.get("/forecast", response_model=ForecastOut)
def forecast(
    business_id: uuid.UUID,
    horizon_days: int = Query(7, ge=1, le=90),
    category_id: uuid.UUID | None = None,
    all_branches: bool = Query(default=False, description=_ALL_BRANCHES_DESCRIPTION),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ForecastOut:
    # Not period-scoped like the four routes above (start/end) — a forecast
    # is always forward-looking from "today" in the business's own
    # timezone; horizon_days controls how far ahead, not which historical
    # window to read (that's the lookback window inside get_forecast).
    # category_id only scopes the per-product table — see get_forecast's
    # own comment on why the revenue forecast figure stays whole-business.
    if all_branches:
        group = _resolve_group_or_error(db, business_id=business_id, user_id=membership.user_id)
        summary = get_forecast_for_group(
            db, businesses=group, horizon_days=horizon_days, category_id=category_id
        )
    else:
        summary = get_forecast(db, business_id=business_id, horizon_days=horizon_days, category_id=category_id)
    return ForecastOut.model_validate(summary)
