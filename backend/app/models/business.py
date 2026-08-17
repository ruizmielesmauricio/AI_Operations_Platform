import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TimestampMixin


class Business(Base, PKMixin, TimestampMixin):
    """The tenant root. Every other table scopes itself to a business via
    business_id (see TenantScopedMixin) — this is the row that id refers to.
    """

    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False, default="bicycle_shop")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Dublin")
    # NULL = a standalone/primary shop — the one-shop-per-account limit
    # (app/repositories/business.py::count_owned_standalone_businesses)
    # counts exactly these. Non-null marks a branch of that parent, set via
    # POST /businesses/{id}/branches (app/repositories/business.py::
    # create_branch_business).
    parent_business_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("businesses.id"), nullable=True
    )
    # Soft-delete marker — a nullable timestamp, not a boolean, mirroring
    # the existing pattern elsewhere in this schema (e.g.
    # import_records.reversed_at). Deleting a business archives it
    # (hidden from listings, its Stripe subscription cancelled) without
    # touching any of its existing sales/products/uploads/audit rows —
    # confirmed with the user: no cascading hard delete exists or is
    # wanted, consistent with this codebase's audit-log-conscious posture.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Profile fields (all optional) ---------------------------------
    # Descriptive contact/location record-keeping only — confirmed with
    # the user this is NOT a second login/account (that would need an
    # invite + permissions system that doesn't exist anywhere in this
    # codebase yet), just richer, human-readable identification per
    # business, most useful once an account has multiple locations.
    # Split into first/surname (not one combined field, direct request) —
    # was a single manager_name column; migrated with a best-effort split
    # on the first space for any pre-existing data.
    manager_first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manager_surname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A short label distinct from `name`, e.g. "Dublin - Rathmines" — the
    # formal shop name is often identical across a primary shop and its
    # branches, so it alone doesn't distinguish them in a list.
    location_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Doubles as the "has a logo at all" flag (NULL = none) and lets
    # GET /businesses/{id}/logo serve the right Content-Type without
    # sniffing or a second stored key/extension column — the R2 object
    # key is always deterministic (logos/{business_id}/logo, computed on
    # the fly in app/api/businesses.py, never stored), so a re-upload
    # just overwrites it and there's never an orphaned old logo to clean
    # up.
    logo_content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
