from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.repositories.product import ProductCategoryRepository
from app.schemas.analytics import ProductCategoryOut
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
