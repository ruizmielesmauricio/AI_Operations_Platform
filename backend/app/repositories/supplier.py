import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.inventory_movement import InventoryMovement
from app.models.supplier import ProductSupplier, Supplier

_SEARCH_LIMIT = 5


class SupplierRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_business(self, business_id: uuid.UUID, *, include_merged: bool = False) -> list[Supplier]:
        # Merged-away suppliers are excluded by default — the merge
        # target is the only one that should appear in a normal list;
        # include_merged=True is only used by the merge-target lookup
        # itself and a future audit view, never the everyday supplier
        # list UI.
        conditions = [Supplier.business_id == business_id, Supplier.status != "deleted"]
        if not include_merged:
            conditions.append(Supplier.status != "merged")
        return list(self.session.scalars(select(Supplier).where(*conditions).order_by(Supplier.name)))

    def get_for_business(self, business_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier | None:
        return self.session.scalar(
            select(Supplier).where(Supplier.business_id == business_id, Supplier.id == supplier_id)
        )

    def search_by_name(self, business_id: uuid.UUID, query: str, *, limit: int = _SEARCH_LIMIT) -> list[Supplier]:
        """Backs the global search bar's "suppliers" group. Same
        active/not-merged exclusion as list_for_business — a deleted or
        merged-away supplier is never a useful search hit, only a stale
        record a caller could otherwise mistake for a real one."""
        needle = f"%{query.strip()}%"
        return list(
            self.session.scalars(
                select(Supplier)
                .where(
                    Supplier.business_id == business_id,
                    Supplier.status == "active",
                    or_(Supplier.name.ilike(needle), Supplier.contact_info.ilike(needle)),
                )
                .order_by(Supplier.name)
                .limit(limit)
            )
        )

    def create(
        self, *, business_id: uuid.UUID, name: str, contact_info: str | None = None
    ) -> Supplier:
        supplier = Supplier(
            business_id=business_id,
            name=name,
            normalized_name=normalize_supplier_name(name),
            contact_info=contact_info,
            status="active",
        )
        self.session.add(supplier)
        self.session.flush()
        return supplier

    def update(
        self, supplier: Supplier, *, name: str | None = None, contact_info: str | None = None
    ) -> Supplier:
        if name is not None:
            supplier.name = name
            supplier.normalized_name = normalize_supplier_name(name)
        if contact_info is not None:
            supplier.contact_info = contact_info
        self.session.flush()
        return supplier

    def find_by_normalized_name(self, business_id: uuid.UUID, normalized_name: str) -> Supplier | None:
        # Never matches a merged/deleted supplier — a name that used to
        # belong to a now-merged-away row should create/match the survivor
        # under its own name instead, not silently resurrect the old row.
        return self.session.scalar(
            select(Supplier).where(
                Supplier.business_id == business_id,
                Supplier.normalized_name == normalized_name,
                Supplier.status == "active",
            )
        )

    def deactivate(self, supplier: Supplier) -> Supplier:
        supplier.status = "deleted"
        self.session.flush()
        return supplier

    def merge(self, *, business_id: uuid.UUID, source: Supplier, target: Supplier) -> dict:
        """Reassigns every product_suppliers/inventory_movements row
        pointing at `source` to `target`, then marks `source` merged
        (soft, never deleted — see Supplier.merged_into_id's docstring).
        Idempotent: re-running against an already-merged source is a
        no-op (it has no active rows left to reassign, and re-marking it
        merged into the same target changes nothing observable).

        Deduplicates product_suppliers on (product_id, supplier_id) —
        reassigning a row that would collide with one target already has
        is deleted instead of creating a duplicate pair; the richer of
        the two (whichever already has a lead_time_days/supplier_sku set)
        wins when both are populated, never silently dropping known data.
        """
        assert source.business_id == business_id and target.business_id == business_id

        # inventory_movements: no uniqueness constraint to worry about,
        # a straight reassignment.
        self.session.execute(
            InventoryMovement.__table__.update()
            .where(InventoryMovement.business_id == business_id, InventoryMovement.supplier_id == source.id)
            .values(supplier_id=target.id)
        )

        source_links = list(
            self.session.scalars(
                select(ProductSupplier).where(
                    ProductSupplier.business_id == business_id, ProductSupplier.supplier_id == source.id
                )
            )
        )
        reassigned = 0
        for link in source_links:
            existing_target_link = self.session.scalar(
                select(ProductSupplier).where(
                    ProductSupplier.business_id == business_id,
                    ProductSupplier.product_id == link.product_id,
                    ProductSupplier.supplier_id == target.id,
                )
            )
            if existing_target_link is None:
                link.supplier_id = target.id
                reassigned += 1
            else:
                # Target already links this product — keep whichever row
                # has more known data, delete the other rather than
                # violate the (product_id, supplier_id) unique constraint.
                if existing_target_link.lead_time_days is None and link.lead_time_days is not None:
                    existing_target_link.lead_time_days = link.lead_time_days
                if existing_target_link.supplier_sku is None and link.supplier_sku is not None:
                    existing_target_link.supplier_sku = link.supplier_sku
                self.session.delete(link)

        source.status = "merged"
        source.merged_into_id = target.id
        self.session.flush()
        return {"inventory_movements_reassigned": True, "product_links_reassigned": reassigned}

    # --- product<->supplier links ------------------------------------

    def get_product_supplier(
        self, business_id: uuid.UUID, *, product_id: uuid.UUID, supplier_id: uuid.UUID
    ) -> ProductSupplier | None:
        return self.session.scalar(
            select(ProductSupplier).where(
                ProductSupplier.business_id == business_id,
                ProductSupplier.product_id == product_id,
                ProductSupplier.supplier_id == supplier_id,
            )
        )

    def upsert_product_supplier(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        supplier_id: uuid.UUID,
        supplier_sku: str | None = None,
    ) -> ProductSupplier:
        # Match-or-create, same "latest wins" semantics as Product.
        # category_id — called once per purchase row that resolved both a
        # product and a supplier. lead_time_days is deliberately never
        # set here: no import path reliably states it, so it stays
        # whatever a manual correction last set (or None), never
        # overwritten by an import.
        link = self.get_product_supplier(business_id, product_id=product_id, supplier_id=supplier_id)
        if link is None:
            link = ProductSupplier(
                business_id=business_id, product_id=product_id, supplier_id=supplier_id, supplier_sku=supplier_sku
            )
            self.session.add(link)
        elif supplier_sku is not None:
            link.supplier_sku = supplier_sku
        self.session.flush()
        return link

    def list_links_for_product(self, business_id: uuid.UUID, product_id: uuid.UUID) -> list[ProductSupplier]:
        return list(
            self.session.scalars(
                select(ProductSupplier).where(
                    ProductSupplier.business_id == business_id, ProductSupplier.product_id == product_id
                )
            )
        )

    def preferred_lead_time_days(self, business_id: uuid.UUID, product_id: uuid.UUID) -> Decimal | None:
        """The shortest known lead time across a product's linked
        suppliers — a deliberately simple, explainable "preferred"
        resolution (no per-product default-supplier concept exists yet)
        for app/analytics/replenishment.py's threshold recommendation.
        None when no link has a lead time recorded at all.
        """
        return self.session.scalar(
            select(func.min(ProductSupplier.lead_time_days)).where(
                ProductSupplier.business_id == business_id,
                ProductSupplier.product_id == product_id,
                ProductSupplier.lead_time_days.isnot(None),
            )
        )

    # --- analytics ------------------------------------------------------

    def spend_by_supplier_in_range(self, business_id: uuid.UUID, start, end) -> list[dict]:
        """Deterministic aggregate for the supplier analytics surface —
        purchase spend/product-count/purchase-count per supplier in a
        date range, same shape/role as app/analytics/category.py's
        per-category aggregation, one level up (supplier instead of
        category). "Unknown supplier" (supplier_id IS NULL) is included
        as its own row so its share is visible, not silently dropped.
        """
        rows = self.session.execute(
            select(
                InventoryMovement.supplier_id,
                func.sum(InventoryMovement.quantity_delta * InventoryMovement.unit_cost).label("spend"),
                func.count(func.distinct(InventoryMovement.product_id)).label("product_count"),
                func.count(InventoryMovement.id).label("purchase_count"),
            )
            .where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.reason == "purchase",
                InventoryMovement.event_date >= start,
                InventoryMovement.event_date < end,
                InventoryMovement.unit_cost.isnot(None),
            )
            .group_by(InventoryMovement.supplier_id)
        ).all()
        return [
            {
                "supplier_id": r.supplier_id,
                "spend": Decimal(r.spend or 0),
                "product_count": int(r.product_count or 0),
                "purchase_count": int(r.purchase_count or 0),
            }
            for r in rows
        ]


def normalize_supplier_name(name: str) -> str:
    return " ".join(name.strip().split()).lower()
