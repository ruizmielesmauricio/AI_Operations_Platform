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
    # counts exactly these. Non-null marks a branch of that parent.
    # Schema groundwork only for now — no route can set this yet; the
    # paid branch checkout flow is a deliberately deferred follow-up.
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
