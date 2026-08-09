from sqlalchemy import DECIMAL, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

SUPPLIER_STATUSES = ("active", "merged", "deleted")


class Supplier(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Schema-only since the initial migration (name/contact_info) — this
    round gives it its first writer (the purchases upload's optional
    `supplier` column, match-or-create by normalized name, same pattern
    as ProductCategory) plus the fields a real merge/correction workflow
    needs.
    """

    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Match-or-create key (app/imports/importer.py::SupplierMatcher,
    # mirrors CategoryMatcher exactly) — lowercased/whitespace-collapsed
    # `name`, never shown to a user, only compared against.
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_info: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Set only when status == "merged" — the surviving supplier this one
    # was folded into. Kept (not hard-deleted) so a merge's audit trail
    # and any stale external reference stay traceable, same soft-delete
    # posture as soft_delete_business.
    merged_into_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)


class ProductSupplier(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Which supplier(s) a product has been bought from, plus what's known
    about buying from that specific supplier — a product can have more
    than one real-world supplier, so this is a many-to-many join, not a
    single FK on Product. Rows are created/updated (never deleted) by the
    purchases importer's match-or-create pass; a merge repoints every row
    from the merged-away supplier_id to the survivor's, deduplicating on
    (product_id, supplier_id) rather than leaving two rows for the same
    pair.
    """

    __tablename__ = "product_suppliers"

    product_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    supplier_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id"), nullable=False, index=True)
    # From a mapped supplier-SKU/reference upload column, if present —
    # optional, never required.
    supplier_sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Days from order to delivery, manually entered (no import path
    # captures this yet — no upload file reliably states it) — feeds
    # app/analytics/replenishment.py's recommended low-stock threshold
    # when set. Nullable: "unknown lead time" is a normal, expected state,
    # never a required field.
    lead_time_days: Mapped[object | None] = mapped_column(DECIMAL(6, 2), nullable=True)
