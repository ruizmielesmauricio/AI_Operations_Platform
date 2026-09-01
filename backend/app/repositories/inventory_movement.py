import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.analytics.types import ProductPurchaseCostAggregate
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.text_normalize import normalize_dashes, normalize_dashes_column
from app.models.supplier import Supplier

_STOCK_AFFECTING_REASONS = ("sale", "purchase", "return", "production_consumption", "production_output")
_LOOKUP_LIMIT = 10
_SEARCH_LIMIT = 5


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
        unit_cost: Decimal | None = None,
        supplier_id: uuid.UUID | None = None,
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
            unit_cost=unit_cost,
            supplier_id=supplier_id,
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
        reconciliation) movement that actually recorded an absolute count
        (resulting_quantity_on_hand IS NOT NULL) is the baseline (0 if the
        product has never been reconciled) — every sale/purchase/return/
        production movement dated *after* that baseline's event_date is
        added on top; anything dated on or before it is presumed already
        reflected in that count and excluded. A movement with no
        event_date at all (legacy rows from before this field existed) is
        always included — the safe default, matching this system's
        behavior before event_date existed.

        A legacy "adjustment" row with no resulting_quantity_on_hand at
        all (written before that column existed — migration
        8b3e6c1a4f92 backfills event_date for these but, correctly, does
        not invent a resulting_quantity_on_hand it has no way to know)
        must never be picked as this baseline: found live during the
        Sales Backdating/Stock Integrity audit, treating a missing value
        the same as a real "0 units counted" (the old `resulting_qty or
        0` did exactly this) silently discarded that row's entire
        historical stock down to zero the moment it became the most
        recent adjustment. Such a row is instead folded into the ordinary
        additive movements below, using its own quantity_delta — under
        the pre-event_date model this delta *was* the row's real
        contribution to a flat running sum, so summing it here (subject
        to the same baseline-date cutoff as every other movement)
        reconstructs the old total exactly when no valid baseline exists,
        and is correctly excluded once a real, valued reconciliation
        supersedes it.

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
                InventoryMovement.quantity_delta,
                InventoryMovement.created_at,
            ).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.product_id.in_(product_ids),
                InventoryMovement.reason == "adjustment",
            )
        ).all()
        # Latest *valued* reconciliation per product — event_date DESC,
        # created_at DESC as a tiebreak (two reconciliations dated the same
        # day; the one processed later wins, matching this business's own
        # understanding of which was more recent). Rows with no recorded
        # resulting_quantity_on_hand (legacy, pre-migration) are excluded
        # from baseline candidacy entirely here — see the docstring above —
        # and collected into legacy_movements instead, to be folded into
        # the ordinary additive pass below like any other movement. A
        # product with no valued adjustment at all simply never appears
        # here — baseline 0, no cutoff date.
        # Stored as {product_id: (sort_key, resulting_qty, cutoff_date)}.
        latest_adjustment: dict[uuid.UUID, tuple[tuple, int, date | None]] = {}
        legacy_movements: list[tuple[uuid.UUID, date | None, int]] = []
        for product_id, event_date_value, resulting_qty, quantity_delta, created_at in adjustment_rows:
            if resulting_qty is None:
                legacy_movements.append((product_id, event_date_value, quantity_delta))
                continue
            sort_key = (event_date_value or date.min, created_at)
            existing = latest_adjustment.get(product_id)
            if existing is None or sort_key > existing[0]:
                latest_adjustment[product_id] = (sort_key, resulting_qty, event_date_value)

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
        for product_id, event_date_value, quantity_delta in [*movement_rows, *legacy_movements]:
            baseline = latest_adjustment.get(product_id)
            cutoff = baseline[2] if baseline else None
            if cutoff is not None and event_date_value is not None and event_date_value <= cutoff:
                continue  # already reflected in the later stock count — not added again
            totals[product_id] = totals.get(product_id, 0) + quantity_delta

        return totals

    def list_purchases(
        self,
        business_id: uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        purchase_reference: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = _LOOKUP_LIMIT,
    ) -> list[InventoryMovement]:
        """Backs ORLA's purchase_lookup chat intent ("what did I order
        under PO-123" / "when did X get delivered") — a single purchase
        is just one reason="purchase" row (purchase_reference/event_date/
        quantity_delta are all stored per-row already), never a separate
        query before now. Every filter is optional and AND-ed together;
        the caller picks whichever combination the question actually
        gave (a reference, a product, a date range, or several). A
        `purchase_reference` filter is a case-insensitive substring
        match, not exact — real references get typo'd/abbreviated in
        conversation more than product SKUs do. Most-recent-first,
        capped at `limit` for the same prompt-size/UX reason
        ProductRepository.search_by_name_or_sku is capped.
        """
        conditions = [InventoryMovement.business_id == business_id, InventoryMovement.reason == "purchase"]
        if product_id is not None:
            conditions.append(InventoryMovement.product_id == product_id)
        if purchase_reference is not None:
            # Dash/hyphen-normalized on both sides — same real bug class
            # as ProductRepository.search_by_name_or_sku (see
            # app/text_normalize.py): a PO reference typed or pasted
            # with a non-ASCII dash shouldn't silently fail to match a
            # reference stored with a plain one.
            needle = normalize_dashes(purchase_reference.strip().upper())
            conditions.append(
                func.upper(normalize_dashes_column(InventoryMovement.purchase_reference)).like(f"%{needle}%")
            )
        if start is not None:
            conditions.append(InventoryMovement.event_date >= start)
        if end is not None:
            conditions.append(InventoryMovement.event_date <= end)
        return list(
            self.session.scalars(
                select(InventoryMovement)
                .where(*conditions)
                .order_by(InventoryMovement.event_date.desc())
                .limit(limit)
            )
        )

    def aggregate_purchase_cost_by_product_in_range(
        self, business_id: uuid.UUID, start: date, end: date
    ) -> list[ProductPurchaseCostAggregate]:
        """Per-product purchase quantity/cost totals for [start, end]
        (both inclusive — event_date is a plain calendar date, same
        convention as list_purchases above, not the half-open UTC-
        datetime convention MetricPeriod uses for timestamp columns).
        Feeds category/product "expenses" (app/analytics/category.py).

        cost only sums rows where unit_cost is known — most purchase
        rows predate that column (see InventoryMovement.unit_cost's own
        docstring), so silently treating an unknown cost as zero would
        understate expenses without any way to tell. quantity_received
        counts every row regardless; quantity_received_with_known_cost
        lets the caller report how much of that quantity's cost is
        actually reflected in `cost`, mirroring the same known/unknown
        completeness split ProductPeriodAggregate already uses for COGS.
        """
        known_cost = InventoryMovement.unit_cost.isnot(None)
        line_cost = InventoryMovement.quantity_delta * InventoryMovement.unit_cost

        rows = self.session.execute(
            select(
                InventoryMovement.product_id,
                func.sum(InventoryMovement.quantity_delta),
                func.sum(case((known_cost, InventoryMovement.quantity_delta), else_=0)),
                func.sum(case((known_cost, line_cost), else_=0)),
            )
            .where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.reason == "purchase",
                InventoryMovement.event_date >= start,
                InventoryMovement.event_date <= end,
            )
            .group_by(InventoryMovement.product_id)
        ).all()

        return [
            ProductPurchaseCostAggregate(
                product_id=product_id,
                quantity_received=int(quantity_received or 0),
                quantity_received_with_known_cost=int(quantity_known or 0),
                cost=Decimal(cost or 0),
            )
            for product_id, quantity_received, quantity_known, cost in rows
        ]

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
        counting stock received (app/imports/importer.py::write_purchases_batch).

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
        """Every product's most recent *valued* "adjustment" movement's
        event_date (skips products with no adjustment at all, whose latest
        one has no event_date, or whose latest one has no recorded
        resulting_quantity_on_hand — a legacy, pre-migration row that
        sum_by_product_ids itself no longer treats as a usable baseline;
        see that method's own docstring) — business-wide, not
        product_ids-scoped, since callers here
        (app/imports/importer.py::write_purchases_batch, _write_sales) resolve
        products row by row as they go, not from a known list upfront.
        Used only to decide whether to show an informational "this
        purchase/sale predates your last stock count" warning — never to
        exclude anything from being written; sum_by_product_ids's own
        (product-scoped) version of this same lookup is what actually
        governs current-stock correctness, and this must stay in sync with
        which adjustment rows it actually treats as a baseline, or the
        warning would fire (or stay silent) inconsistently with reality."""
        rows = self.session.execute(
            select(InventoryMovement.product_id, InventoryMovement.event_date, InventoryMovement.created_at).where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.reason == "adjustment",
                InventoryMovement.event_date.isnot(None),
                InventoryMovement.resulting_quantity_on_hand.isnot(None),
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

    def search_purchases(
        self, business_id: uuid.UUID, query: str, *, limit: int = _SEARCH_LIMIT
    ) -> list[tuple[InventoryMovement, Product | None, Supplier | None]]:
        """Backs the global search bar's "purchases" group — OR across
        purchase_reference, the related product's name/SKU, and the
        related supplier's name. Deliberately separate from list_purchases
        above (ORLA chat lookup — a single named filter, never OR'd
        together) and list_purchases_paginated (the Transactions page's
        AND-per-filter shape) — a search bar has one field."""
        needle = f"%{query.strip()}%"
        return [
            (movement, product, supplier)
            for movement, product, supplier in self.session.execute(
                select(InventoryMovement, Product, Supplier)
                .outerjoin(Product, Product.id == InventoryMovement.product_id)
                .outerjoin(Supplier, Supplier.id == InventoryMovement.supplier_id)
                .where(
                    InventoryMovement.business_id == business_id,
                    InventoryMovement.reason == "purchase",
                    or_(
                        InventoryMovement.purchase_reference.ilike(needle),
                        Product.name.ilike(needle),
                        Product.sku.ilike(needle),
                        Supplier.name.ilike(needle),
                    ),
                )
                .order_by(InventoryMovement.event_date.desc(), InventoryMovement.id.desc())
                .limit(limit)
            ).all()
        ]

    def list_purchases_paginated(
        self,
        business_id: uuid.UUID,
        *,
        start: date | None = None,
        end: date | None = None,
        product_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[tuple[InventoryMovement, Product | None, Supplier | None]], int]:
        """Raw, one-purchase-row-per-item listing behind the dashboard's
        transaction drill-down (Gap 5) — deliberately separate from
        list_purchases above (ORLA chat lookup, fixed low limit, no
        pagination/category filter) and aggregate_purchase_cost_by_product_
        in_range (per-product sums only). Every filter optional and
        AND-ed; category_id requires the outer join to Product.
        Most-recent-first, stable (event_date, id) ordering.
        """
        conditions = [InventoryMovement.business_id == business_id, InventoryMovement.reason == "purchase"]
        if start is not None:
            conditions.append(InventoryMovement.event_date >= start)
        if end is not None:
            conditions.append(InventoryMovement.event_date <= end)
        if product_id is not None:
            conditions.append(InventoryMovement.product_id == product_id)
        if category_id is not None:
            conditions.append(Product.category_id == category_id)

        base = (
            select(InventoryMovement, Product, Supplier)
            .outerjoin(Product, Product.id == InventoryMovement.product_id)
            .outerjoin(Supplier, Supplier.id == InventoryMovement.supplier_id)
            .where(*conditions)
        )
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.execute(
            base.order_by(InventoryMovement.event_date.desc(), InventoryMovement.id.desc()).limit(limit).offset(offset)
        ).all()
        return [(movement, product, supplier) for movement, product, supplier in rows], total

    def list_purchases_by_unit_cost(
        self,
        business_id: uuid.UUID,
        *,
        limit: int = 10,
    ) -> list[tuple[InventoryMovement, Product | None, Supplier | None]]:
        """Most expensive purchase rows by recorded per-unit cost.
        This backs ORLA list-style purchase-history questions such as
        "what were the most expensive things I ordered by unit?" Unit
        cost can be null on older imports, so those rows are excluded
        rather than treated as free/zero-cost purchases."""
        rows = self.session.execute(
            select(InventoryMovement, Product, Supplier)
            .outerjoin(Product, Product.id == InventoryMovement.product_id)
            .outerjoin(Supplier, Supplier.id == InventoryMovement.supplier_id)
            .where(
                InventoryMovement.business_id == business_id,
                InventoryMovement.reason == "purchase",
                InventoryMovement.unit_cost.isnot(None),
            )
            .order_by(InventoryMovement.unit_cost.desc(), InventoryMovement.event_date.desc(), InventoryMovement.id.desc())
            .limit(limit)
        ).all()
        return [(movement, product, supplier) for movement, product, supplier in rows]
