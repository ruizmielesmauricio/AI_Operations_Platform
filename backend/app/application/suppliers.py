"""Orchestrates supplier CRUD/merge/manual-correction and the supplier
spend analytics surface. No calculation logic of its own beyond simple
period resolution — see CLAUDE.md's "Business Logic First".
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analytics.period import resolve_period
from app.models.business import Business
from app.models.product import Product
from app.models.supplier import ProductSupplier, Supplier
from app.repositories.audit_log import record_audit_event
from app.repositories.supplier import SupplierRepository, normalize_supplier_name


class SupplierNotFound(Exception):
    pass


class ProductNotFound(Exception):
    pass


class CannotMergeSupplierIntoItself(Exception):
    pass


def list_suppliers(db: Session, business_id: uuid.UUID) -> list[Supplier]:
    return SupplierRepository(db).list_for_business(business_id)


def create_supplier(
    db: Session, *, business_id: uuid.UUID, name: str, contact_info: str | None, creating_user_id: str
) -> tuple[Supplier, bool]:
    """Match-or-create by normalized name — same "avoid duplicate
    creation where a reasonable match exists" rule the import path uses
    (app/imports/importer.py::SupplierMatcher), applied here too so a
    manually-added supplier and an imported one never end up as two
    separate rows for the same real-world supplier. Returns
    (supplier, created) so the caller/UI can say "matched an existing
    supplier" vs "created a new one" instead of staying silent about it.
    """
    repo = SupplierRepository(db)
    existing = repo.find_by_normalized_name(business_id, normalize_supplier_name(name))
    if existing is not None:
        return existing, False
    supplier = repo.create(business_id=business_id, name=name, contact_info=contact_info)
    record_audit_event(
        db, business_id=business_id, user_id=creating_user_id, action="supplier_created",
        target_type="supplier", target_id=str(supplier.id),
    )
    db.commit()
    db.refresh(supplier)
    return supplier, True


def update_supplier(
    db: Session,
    *,
    business_id: uuid.UUID,
    supplier_id: uuid.UUID,
    name: str | None,
    contact_info: str | None,
    editing_user_id: str,
) -> Supplier:
    repo = SupplierRepository(db)
    supplier = repo.get_for_business(business_id, supplier_id)
    if supplier is None or supplier.status == "deleted":
        raise SupplierNotFound(str(supplier_id))
    repo.update(supplier, name=name, contact_info=contact_info)
    record_audit_event(
        db, business_id=business_id, user_id=editing_user_id, action="supplier_edited",
        target_type="supplier", target_id=str(supplier.id),
    )
    db.commit()
    db.refresh(supplier)
    return supplier


def deactivate_supplier(
    db: Session, *, business_id: uuid.UUID, supplier_id: uuid.UUID, deleting_user_id: str
) -> Supplier:
    repo = SupplierRepository(db)
    supplier = repo.get_for_business(business_id, supplier_id)
    if supplier is None:
        raise SupplierNotFound(str(supplier_id))
    if supplier.status == "deleted":
        return supplier  # idempotent, mirrors delete_employee's own precedent
    repo.deactivate(supplier)
    record_audit_event(
        db, business_id=business_id, user_id=deleting_user_id, action="supplier_deactivated",
        target_type="supplier", target_id=str(supplier.id),
    )
    db.commit()
    db.refresh(supplier)
    return supplier


def merge_suppliers(
    db: Session, *, business_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID, merging_user_id: str
) -> Supplier:
    if source_id == target_id:
        raise CannotMergeSupplierIntoItself(str(source_id))
    repo = SupplierRepository(db)
    source = repo.get_for_business(business_id, source_id)
    target = repo.get_for_business(business_id, target_id)
    if source is None or target is None:
        raise SupplierNotFound(str(source_id if source is None else target_id))
    if source.status == "merged":
        # Idempotent: a source already merged (into this same target or
        # any other) has nothing left to reassign — re-running the same
        # merge call changes nothing observable, matching
        # delete_employee's precedent for the same reasoning.
        return target
    result = repo.merge(business_id=business_id, source=source, target=target)
    record_audit_event(
        db, business_id=business_id, user_id=merging_user_id, action="supplier_merged",
        target_type="supplier", target_id=str(target.id),
        metadata={"merged_supplier_id": str(source.id), **result},
    )
    db.commit()
    db.refresh(target)
    return target


def correct_product_supplier(
    db: Session,
    *,
    business_id: uuid.UUID,
    product_id: uuid.UUID,
    supplier_id: uuid.UUID,
    supplier_sku: str | None,
    lead_time_days: Decimal | None,
    editing_user_id: str,
) -> ProductSupplier:
    """The only path lead_time_days is ever set through — no upload file
    reliably states it, so this manual-correction route is where an
    owner records it (or fixes a wrong auto-matched supplier link) after
    the fact.
    """
    supplier_repo = SupplierRepository(db)
    supplier = supplier_repo.get_for_business(business_id, supplier_id)
    if supplier is None:
        raise SupplierNotFound(str(supplier_id))
    product = db.get(Product, product_id)
    if product is None or product.business_id != business_id:
        raise ProductNotFound(str(product_id))

    link = supplier_repo.upsert_product_supplier(
        business_id=business_id, product_id=product_id, supplier_id=supplier_id, supplier_sku=supplier_sku
    )
    if lead_time_days is not None:
        link.lead_time_days = lead_time_days
        db.flush()
    record_audit_event(
        db, business_id=business_id, user_id=editing_user_id, action="purchase_supplier_corrected",
        target_type="product_supplier", target_id=str(link.id),
        metadata={"product_id": str(product_id), "supplier_id": str(supplier_id)},
    )
    db.commit()
    db.refresh(link)
    return link


@dataclass(frozen=True)
class SupplierSpendRow:
    supplier_id: uuid.UUID | None  # None means "unknown supplier"
    supplier_name: str  # "Unknown" when supplier_id is None
    spend: Decimal
    product_count: int
    purchase_count: int


@dataclass(frozen=True)
class SupplierAnalyticsSummary:
    start: date
    end: date
    rows: list[SupplierSpendRow]
    unknown_supplier_share_pct: Decimal | None


def get_supplier_analytics(
    db: Session, *, business_id: uuid.UUID, start_date: date | None, end_date: date | None
) -> SupplierAnalyticsSummary:
    business = db.get(Business, business_id)
    if business is None:
        raise ValueError(f"Business {business_id} not found")

    period = resolve_period(business.timezone, start_date, end_date)
    supplier_repo = SupplierRepository(db)
    raw_rows = supplier_repo.spend_by_supplier_in_range(business_id, period.start.date(), period.end.date())

    suppliers_by_id = {s.id: s for s in supplier_repo.list_for_business(business_id, include_merged=True)}
    rows = [
        SupplierSpendRow(
            supplier_id=r["supplier_id"],
            supplier_name=suppliers_by_id[r["supplier_id"]].name if r["supplier_id"] is not None else "Unknown",
            spend=r["spend"],
            product_count=r["product_count"],
            purchase_count=r["purchase_count"],
        )
        for r in raw_rows
    ]
    rows.sort(key=lambda r: r.spend, reverse=True)

    total_spend = sum((r.spend for r in rows), Decimal("0"))
    unknown_spend = sum((r.spend for r in rows if r.supplier_id is None), Decimal("0"))
    unknown_share = (
        (unknown_spend / total_spend * 100).quantize(Decimal("0.1")) if total_spend > 0 else None
    )

    return SupplierAnalyticsSummary(
        start=period.start.date(), end=period.end.date(), rows=rows, unknown_supplier_share_pct=unknown_share
    )
