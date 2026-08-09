import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.products import CategoryNotFound, update_category_threshold
from app.models.membership import Membership
from app.repositories.product import ProductCategoryRepository
from app.schemas.analytics import ProductCategoryOut
from app.schemas.product import CategoryThresholdUpdate
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/product-categories", tags=["product-categories"])


@router.get("", response_model=list[ProductCategoryOut])
def list_product_categories(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[ProductCategoryOut]:
    # Read-only — populates the dashboard's per-section category filter
    # dropdowns. No create/edit endpoint yet; every category today is
    # created organically via an import's optional "category" column
    # (see app/imports/importer.py's CategoryMatcher).
    categories = ProductCategoryRepository(db).list_for_business(membership.business_id)
    return [ProductCategoryOut.model_validate(c) for c in categories]


@router.patch("/{category_id}/threshold", response_model=ProductCategoryOut)
def update_category_threshold_route(
    category_id: uuid.UUID,
    payload: CategoryThresholdUpdate,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> ProductCategoryOut:
    # Owner/manager only — the low-stock threshold is a business-
    # configuration setting, same role bar as supplier management.
    if membership.role not in ("owner", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner or manager can change thresholds"
        )
    try:
        update_category_threshold(
            db,
            business_id=membership.business_id,
            category_id=category_id,
            threshold_days=payload.threshold_days,
            editing_user_id=current_user.id,
        )
    except CategoryNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found") from exc
    category = ProductCategoryRepository(db).get_for_business(membership.business_id, category_id)
    return ProductCategoryOut.model_validate(category)
