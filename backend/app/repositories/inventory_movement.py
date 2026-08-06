import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.inventory_movement import InventoryMovement

_STOCK_AFFECTING_REASONS = ("sale", "purchase", "return", "production_consumption", "production_output")


class InventoryMovementRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity_delta: int,
        reason: str,
        reference_id: uuid.UUID | None = None,
        import_record_id: uuid.UUID | None = None,
        purchase_reference: str | None = None,
        event_date: date | None = None,
        resulting_quantity_on_hand: int | None = None,
    ) -> InventoryMovement:
        # Flush only — app/imports/importer.py owns the single commit.
        movement = InventoryMovement(
            business_id=business_id,
            product_id=product_id,
            quantity_delta=quantity_delta,
            reason=reason,
            reference_id=reference_id,
            import_record_id=import_record_id,
            purchase_reference=purchase_reference,
            event_date=event_date,
            resulting_quantity_on_hand=resulting_quantity_on_hand,
        )
        self.session.add(movement)
        self.session.flush()
        return movement

    def sum_by_product_ids(self, business_id: uuid.UUID, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Current derived stock for each product — order-independent: a
        pure function of *when* things happened (event_date), not of what
        order the underlying files/events were uploaded/processed in.
        Two queries, not N+1 (fetch-raw-then-finish-in-Python, same
        pattern as app/analytics/period.py::group_amounts_by_local_date —
        deliberately avoids Postgres-only window-function SQL to stay
        SQLite-portable for tests).

        Formula per product: the most recent "adjustment" (stock-count
        reconciliation) movement's resulting_quantity_on_hand is the
        baseline (0 if the product has never been reconciled) — every
        sale/purchase/return/production movement dated *after* that
        baseline's event_date is added on top; anything dated on or
        before it is presumed already reflected in that count and
        excluded. A movement with no event_date at all (legacy rows from
        before this field existed) is always included — the safe
        default, matching this system's behavior before event_date
        existed.

        A product with no rows here (never had a movement) has 0 stock;
        callers must default missing keys themselves.
        """
        if not product_ids:
            return {}

        adjustment_rows = self.session.execute(
            select(
                InventoryMovement.product_id,
                InventoryMovement.event_date,
                InventoryMovement.resulting_quantity_on_hand,
                InventoryMovement.created_at,
            ).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.product_id.in_(product_ids),
                InventoryMovement.reason == "adjustment",
            )
        ).all()
        # Latest per product — event_date DESC, created_at DESC as a
        # tiebreak (two reconciliations dated the same day; the one
        # processed later wins, matching this business's own understanding
        # of which was more recent). A product with no adjustment at all
        # simply never appears here — baseline 0, no cutoff date.
        # Stored as {product_id: (sort_key, resulting_qty, cutoff_date)}.
        latest_adjustment: dict[uuid.UUID, tuple[tuple, int, date | None]] = {}
        for product_id, event_date_value, resulting_qty, created_at in adjustment_rows:
            sort_key = (event_date_value or date.min, created_at)
            existing = latest_adjustment.get(product_id)
            if existing is None or sort_key > existing[0]:
                latest_adjustment[product_id] = (sort_key, resulting_qty or 0, event_date_value)

        movement_rows = self.session.execute(
            select(InventoryMovement.product_id, InventoryMovement.event_date, InventoryMovement.quantity_delta).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.product_id.in_(product_ids),
                InventoryMovement.reason.in_(_STOCK_AFFECTING_REASONS),
            )
        ).all()

        totals: dict[uuid.UUID, int] = {
            product_id: resulting_qty for product_id, (_sort_key, resulting_qty, _cutoff) in latest_adjustment.items()
        }
        for product_id, event_date_value, quantity_delta in movement_rows:
            baseline = latest_adjustment.get(product_id)
            cutoff = baseline[2] if baseline else None
            if cutoff is not None and event_date_value is not None and event_date_value <= cutoff:
                continue  # already reflected in the later stock count — not added again
            totals[product_id] = totals.get(product_id, 0) + quantity_delta

        return totals

    def bulk_delete_by_reference_ids(self, sale_item_ids: list[uuid.UUID]) -> None:
        if not sale_item_ids:
            return
        self.session.execute(delete(InventoryMovement).where(InventoryMovement.reference_id.in_(sale_item_ids)))
        self.session.flush()

    def bulk_delete_by_import_record_id(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> None:
        self.session.execute(
            delete(InventoryMovement).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.import_record_id == import_record_id,
            )
        )
        self.session.flush()

    def list_existing_purchase_reference_product_pairs(self, business_id: uuid.UUID) -> set[tuple[str, uuid.UUID]]:
        """Every non-null (purchase_reference, product_id) pair already
        used by this business's purchase movements, across all prior
        imports — one query, not N+1. Used to reject a re-uploaded/
        overlapping purchases file per row instead of silently double-
        counting stock received (app/imports/importer.py::_write_purchases).

        Keyed by reference AND product, not reference alone — a single PO
        / invoice routinely covers several different products in one
        purchase, so two rows sharing a reference are not automatically
        duplicates of each other."""
        rows = self.session.execute(
            select(InventoryMovement.purchase_reference, InventoryMovement.product_id).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.reason == "purchase",
                InventoryMovement.purchase_reference.isnot(None),
            )
        ).all()
        return {(ref, product_id) for ref, product_id in rows}

    def list_latest_adjustment_event_dates(self, business_id: uuid.UUID) -> dict[uuid.UUID, date]:
        """Every product's most recent "adjustment" movement's event_date
        (skips products with no adjustment at all, or whose latest one has
        no event_date) — business-wide, not product_ids-scoped, since
        callers here (app/imports/importer.py::_write_purchases) resolve
        products row by row as they go, not from a known list upfront.
        Used only to decide whether to show an informational "this
        purchase predates your last stock count" warning — never to
        exclude anything from being written; sum_by_product_ids's own
        (product-scoped) version of this same lookup is what actually
        governs current-stock correctness."""
        rows = self.session.execute(
            select(InventoryMovement.product_id, InventoryMovement.event_date, InventoryMovement.created_at).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.reason == "adjustment",
                InventoryMovement.event_date.isnot(None),
            )
        ).all()
        latest: dict[uuid.UUID, tuple[date, object]] = {}
        for product_id, event_date_value, created_at in rows:
            existing = latest.get(product_id)
            if existing is None or (event_date_value, created_at) > existing:
                latest[product_id] = (event_date_value, created_at)
        return {product_id: value[0] for product_id, value in latest.items()}

    def list_product_ids_by_import_record_id(self, business_id: uuid.UUID, import_record_id: uuid.UUID) -> set[uuid.UUID]:
        """Read before app/imports/importer.py's _undo_inventory_import
        deletes these rows — Stage C12 needs to know which products an
        undo touched, to refresh their low-stock alerts afterward."""
        rows = self.session.scalars(
            select(InventoryMovement.product_id).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.import_record_id == import_record_id,
            )
        )
        return set(rows)
