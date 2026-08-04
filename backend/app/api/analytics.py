import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.financial_performance import get_financial_performance
from app.application.findings import get_findings
from app.application.retail_operations import get_retail_operations
from app.models.membership import Membership
from app.schemas.analytics import FindingsOut, FinancialPerformanceOut, RetailOperationsOut
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/analytics", tags=["analytics"])


@router.get("/financial-performance", response_model=FinancialPerformanceOut)
def financial_performance(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> FinancialPerformanceOut:
    summary = get_financial_performance(db, business_id=business_id, start_date=start, end_date=end)
    return FinancialPerformanceOut.model_validate(summary)


@router.get("/retail-operations", response_model=RetailOperationsOut)
def retail_operations(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> RetailOperationsOut:
    summary = get_retail_operations(db, business_id=business_id, start_date=start, end_date=end)
    return RetailOperationsOut.model_validate(summary)


@router.get("/findings", response_model=FindingsOut)
def findings(
    business_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> FindingsOut:
    summary = get_findings(db, business_id=business_id, start_date=start, end_date=end)
    return FindingsOut.model_validate(summary)
