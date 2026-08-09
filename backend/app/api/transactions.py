import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.transactions import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    list_purchase_transactions,
    list_repair_transactions,
    list_sale_transactions,
)
from app.models.membership import Membership
from app.schemas.transaction import (
    PaginatedPurchaseTransactionsOut,
    PaginatedRepairTransactionsOut,
    PaginatedSaleTransactionsOut,
)
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/transactions", tags=["transactions"])

# Any role can view — this is strictly a more granular view of data the
# role can already see aggregated on the dashboard (Dashboard/Reports/
# Uploads all gate on plain get_current_membership too), so no extra
# restriction is added here. Tenant scoping comes entirely from
# membership.business_id — there is no way to pass a different
# business_id through these routes at all, let alone one the caller
# isn't a member of (get_current_membership already 403s on that).


@router.get("/sales", response_model=PaginatedSaleTransactionsOut)
def list_sale_transactions_route(
    start_date: date | None = None,
    end_date: date | None = None,
    product_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> PaginatedSaleTransactionsOut:
    result = list_sale_transactions(
        db,
        business_id=membership.business_id,
        start_date=start_date,
        end_date=end_date,
        product_id=product_id,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedSaleTransactionsOut.model_validate(result)


@router.get("/purchases", response_model=PaginatedPurchaseTransactionsOut)
def list_purchase_transactions_route(
    start_date: date | None = None,
    end_date: date | None = None,
    product_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> PaginatedPurchaseTransactionsOut:
    result = list_purchase_transactions(
        db,
        business_id=membership.business_id,
        start_date=start_date,
        end_date=end_date,
        product_id=product_id,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedPurchaseTransactionsOut.model_validate(result)


@router.get("/repairs", response_model=PaginatedRepairTransactionsOut)
def list_repair_transactions_route(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> PaginatedRepairTransactionsOut:
    result = list_repair_transactions(
        db, business_id=membership.business_id, start_date=start_date, end_date=end_date, limit=limit, offset=offset
    )
    return PaginatedRepairTransactionsOut.model_validate(result)
