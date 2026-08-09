import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.application.suppliers import (
    CannotMergeSupplierIntoItself,
    ProductNotFound,
    SupplierNotFound,
    correct_product_supplier,
    create_supplier,
    deactivate_supplier,
    get_supplier_analytics,
    list_suppliers,
    merge_suppliers,
    update_supplier,
)
from app.models.membership import Membership
from app.schemas.supplier import (
    ProductSupplierCorrection,
    ProductSupplierOut,
    SupplierAnalyticsOut,
    SupplierCreate,
    SupplierCreateResponse,
    SupplierMergeRequest,
    SupplierOut,
    SupplierUpdate,
)
from app.security.auth import AuthenticatedUser, get_current_user_synced
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/suppliers", tags=["suppliers"])

# Owner/manager can manage suppliers (create/edit/merge/deactivate/correct
# a product link) — staff can view (analytics, the list) but not write.
# Same role split as every other business-configuration surface in this
# app (employee seats, business profile).
_WRITE_ROLES = ("owner", "manager")


def _require_write_role(membership: Membership) -> None:
    if membership.role not in _WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner or manager can manage suppliers"
        )


@router.get("", response_model=list[SupplierOut])
def list_suppliers_route(
    membership: Membership = Depends(get_current_membership), db: Session = Depends(get_db)
) -> list[SupplierOut]:
    return [SupplierOut.model_validate(s) for s in list_suppliers(db, membership.business_id)]


@router.post("", response_model=SupplierCreateResponse, status_code=status.HTTP_201_CREATED)
def create_supplier_route(
    payload: SupplierCreate,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> SupplierCreateResponse:
    _require_write_role(membership)
    supplier, created = create_supplier(
        db,
        business_id=membership.business_id,
        name=payload.name,
        contact_info=payload.contact_info,
        creating_user_id=current_user.id,
    )
    return SupplierCreateResponse(supplier=SupplierOut.model_validate(supplier), created=created)


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier_route(
    supplier_id: uuid.UUID,
    payload: SupplierUpdate,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> SupplierOut:
    _require_write_role(membership)
    try:
        supplier = update_supplier(
            db,
            business_id=membership.business_id,
            supplier_id=supplier_id,
            name=payload.name,
            contact_info=payload.contact_info,
            editing_user_id=current_user.id,
        )
    except SupplierNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found") from exc
    return SupplierOut.model_validate(supplier)


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_supplier_route(
    supplier_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> None:
    _require_write_role(membership)
    try:
        deactivate_supplier(
            db, business_id=membership.business_id, supplier_id=supplier_id, deleting_user_id=current_user.id
        )
    except SupplierNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found") from exc


@router.post("/{supplier_id}/merge", response_model=SupplierOut)
def merge_supplier_route(
    supplier_id: uuid.UUID,
    payload: SupplierMergeRequest,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> SupplierOut:
    # Owner-only, not owner-or-manager — merge is destructive/irreversible
    # (per direct requirement: "Owner/admin only" for merge specifically),
    # a stricter bar than the create/edit/deactivate actions above.
    if membership.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the shop's owner can merge suppliers")
    try:
        target = merge_suppliers(
            db,
            business_id=membership.business_id,
            source_id=supplier_id,
            target_id=payload.target_supplier_id,
            merging_user_id=current_user.id,
        )
    except SupplierNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found") from exc
    except CannotMergeSupplierIntoItself as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A supplier cannot be merged into itself"
        ) from exc
    return SupplierOut.model_validate(target)


@router.post("/product-links", response_model=ProductSupplierOut)
def correct_product_supplier_route(
    payload: ProductSupplierCorrection,
    membership: Membership = Depends(get_current_membership),
    current_user: AuthenticatedUser = Depends(get_current_user_synced),
    db: Session = Depends(get_db),
) -> ProductSupplierOut:
    _require_write_role(membership)
    try:
        link = correct_product_supplier(
            db,
            business_id=membership.business_id,
            product_id=payload.product_id,
            supplier_id=payload.supplier_id,
            supplier_sku=payload.supplier_sku,
            lead_time_days=payload.lead_time_days,
            editing_user_id=current_user.id,
        )
    except SupplierNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found") from exc
    except ProductNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found") from exc
    return ProductSupplierOut.model_validate(link)


@router.get("/analytics", response_model=SupplierAnalyticsOut)
def supplier_analytics_route(
    start_date: date | None = None,
    end_date: date | None = None,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> SupplierAnalyticsOut:
    summary = get_supplier_analytics(
        db, business_id=membership.business_id, start_date=start_date, end_date=end_date
    )
    return SupplierAnalyticsOut(
        start=summary.start.isoformat(),
        end=summary.end.isoformat(),
        rows=summary.rows,
        unknown_supplier_share_pct=summary.unknown_supplier_share_pct,
    )
