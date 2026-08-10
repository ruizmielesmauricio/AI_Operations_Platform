import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.products import ProductNotFound, list_product_thresholds, update_product_threshold
from app.models.membership import Membership
from app.schemas.product import ProductThresholdOut, ProductThresholdSaveOut, ProductThresholdUpdate
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/products", tags=["products"])


@router.get("/thresholds", response_model=list[ProductThresholdOut])
def list_product_thresholds_route(
    category_id: uuid.UUID | None = Query(default=None),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[ProductThresholdOut]:
    # Any role can view — same "read is fine, write needs owner/manager"
    # split as suppliers.
    rows = list_product_thresholds(db, business_id=membership.business_id, category_id=category_id)
    return [ProductThresholdOut.model_validate(r) for r in rows]


@router.patch("/{product_id}/threshold", response_model=ProductThresholdSaveOut)
def update_product_threshold_route(
    product_id: uuid.UUID,
    payload: ProductThresholdUpdate,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> ProductThresholdSaveOut:
    if membership.role not in ("owner", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner or manager can change thresholds"
        )
    try:
        product = update_product_threshold(
            db,
            business_id=membership.business_id,
            product_id=product_id,
            threshold_days=payload.threshold_days,
            editing_user_id=current_user.id,
            accepted_recommendation=payload.accepted_recommendation,
        )
    except ProductNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found") from exc
    return ProductThresholdSaveOut(
        product_id=product.id,
        low_stock_threshold_days=product.low_stock_threshold_days,
        low_stock_threshold_source=product.low_stock_threshold_source,
    )
