from datetime import datetime

from sqlalchemy import DECIMAL, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin

EVENT_TYPES = ("repair", "production_batch")

"""Canonical "Production Events" entity (ADR-016, Accepted). Generalises the
former bicycle-shop-specific Repair/RepairPartUsed tables into the pattern
described in 06_Database_Design.md: something is produced or performed
using tracked inputs, and the output is sold.

- Bicycle-shop template: event_type="repair" — input=parts consumed,
  output=a billed service (no ProductionEventOutput row; billed via a
  sale_item, built when Workshop Operations calculations are).
- Coffee-shop template: event_type="production_batch" — input=ingredients,
  output=new sellable stock, recorded via ProductionEventOutput.

event_type is a denormalized discriminator (same rationale as
ImportRecord.entity_type) so queries/UI can filter without joining through
Business.template.

`ProductionEvent` is written by the "repairs" upload entity type
(app/imports/importer.py::_write_repairs) — a shop's own repair log/export,
uploaded periodically, one row per finished repair. It's ingested as
event_type="repair", status="completed" (not the model's "open" default,
which is reserved for a possible future real-time entry screen), with
customer_id/performed_by_id left NULL (no reliable matching key for a free-
text name, same reasoning sales never got customer-matching). No parts-
consumed detail is captured this way — `ProductionEventInput`/
`ProductionEventOutput` remain schema-only, unconsumed by any writer yet.
"""


class ProductionEvent(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "production_events"

    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    customer_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    # Who/what performed it — the mechanic on a repair, the kitchen/baker on
    # a production batch. Employee's own docstring already anticipates this
    # generalised name (it replaces Repair.mechanic_id).
    performed_by_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    labour_cost: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    # Only meaningful for event_type="repair" — a production_batch's value
    # is realised later, when its output sells normally via a sale_item.
    price_charged: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    # Which import created this row, if any (nullable — a future real-time
    # entry screen won't have one). Mirrors Sale.import_record_id — undo
    # (app/imports/importer.py) uses this to find and remove exactly the
    # rows one "repairs" import created.
    import_record_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_records.id"), nullable=True, index=True
    )


class ProductionEventInput(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """What was consumed — parts (repair) or ingredients (production batch).
    cost_price_at_time mirrors SaleItem.cost_price_at_sale: snapshotted so
    historical cost/margin never drifts when Product.cost_price changes.
    """

    __tablename__ = "production_event_inputs"

    production_event_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_events.id"), nullable=False, index=True
    )
    product_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cost_price_at_time: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)


class ProductionEventOutput(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """What was produced — only used when the event's output is new sellable
    stock (a coffee-shop batch). NOT used for repairs, whose output is a
    billed service via a sale_item, not new inventory.
    """

    __tablename__ = "production_event_outputs"

    production_event_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("production_events.id"), nullable=False, index=True
    )
    # NOT NULL (unlike input/sale-line product_id): an output row only
    # exists when a specific sellable product was actually produced.
    product_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
