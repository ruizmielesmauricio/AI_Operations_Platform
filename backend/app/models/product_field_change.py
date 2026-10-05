import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

# The only product fields an import ever overwrites on an EXISTING product
# ("latest value wins" — see ProductRepository.update_cost_price/
# update_sell_price/update_category). Anything else an import touches is
# either creating a new row or additive (a stock movement).
TRACKED_PRODUCT_FIELDS = ("cost_price", "sell_price", "category_id")

CHANGE_STATUSES = ("applied", "reverted", "superseded", "kept_edited")


class ProductFieldChange(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """One value an import overwrote on an existing product, with what it
    was before — so undoing that import can put the previous value back
    instead of leaving the file's value behind (a deleted file must not
    keep changing your prices/categories).

    Values are stored as strings (a Decimal or a category UUID) and parsed
    per `field` on revert. `status` records what undo decided:
    - applied: the import's value is still live; nothing undone yet
    - reverted: undo restored `old_value`
    - superseded: a LATER import overwrote the value after this one, so
      this change was not touched and the later change's own old_value was
      re-pointed past it (undoing that later import still lands on the
      true original, never on a value from a file that no longer counts)
    - kept_edited: the live value no longer matched what this import wrote
      (edited by hand since), so undo left it alone
    """

    __tablename__ = "product_field_changes"

    import_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_records.id"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="applied")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
