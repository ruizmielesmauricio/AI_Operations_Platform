"""B8: turns a confirmed column mapping into real Sale/SaleItem/
InventoryMovement rows (PR-2.6-2.11). Row normalization/validation/
grouping/product-matching are kept as pure functions with no DB or file
I/O, separate from the orchestration that writes them (further down this
module) — the pure half is what's unit-tested directly.
"""

import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.imports import detection, file_parser
from app.imports import r2_client as r2_client_module
from app.imports.exceptions import (
    HeaderRowNotFound,
    ImportNotReversible,
    ImportRecordNotReady,
    ImportSupersededByLaterInventoryImport,
    MappedColumnMissing,
)
from app.imports.file_parser import normalize_cell
from app.imports.service import download_checked
from app.imports.value_parsers import parse_date, parse_int, parse_money
from app.application.alerts import refresh_low_stock_alerts
from app.models.import_record import ImportRecord
from app.models.upload import Upload
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductRepository
from app.repositories.production_event import ProductionEventRepository
from app.repositories.sale import SaleRepository
from app.repositories.sale_item import SaleItemRepository
from app.repositories.upload import UploadRepository

logger = logging.getLogger(__name__)

Row = list[object]

# Distinct from B7's 215-row detection window — B8 needs every row, this is
# just a sanity ceiling.
_MAX_IMPORT_ROWS = 200_000
_SAMPLE_CAP = 20

_CENTS = Decimal("0.01")
_MISMATCH_TOLERANCE = Decimal("0.01")


@dataclass
class ParsedSaleRow:
    row_number: int  # spreadsheet-visible, 1-indexed
    sale_date: date
    product_name: str | None
    sku: str | None
    quantity: int
    unit_price: Decimal
    cost_price_at_sale: Decimal | None
    order_reference: str | None
    total_amount_mismatch: bool = False


@dataclass
class ParsedInventoryRow:
    row_number: int  # spreadsheet-visible, 1-indexed
    product_name: str | None
    sku: str | None
    quantity_on_hand: int


@dataclass
class ParsedPurchaseRow:
    row_number: int  # spreadsheet-visible, 1-indexed
    purchase_date: date
    product_name: str | None
    sku: str | None
    quantity_received: int
    unit_cost: Decimal | None


@dataclass
class ParsedRepairRow:
    row_number: int  # spreadsheet-visible, 1-indexed
    repair_date: date
    description: str | None
    price_charged: Decimal | None
    labour_cost: Decimal | None


@dataclass
class RejectedRow:
    row_number: int
    code: str
    raw: dict[str, str]


def extract_mapped_values(row: Row, column_index_by_field: dict[str, int]) -> dict[str, object]:
    """Pulls each mapped canonical field's raw cell value (native type) out
    of a grid row. Only includes keys for fields that were actually mapped
    to a column — a field's absence here means "not present in this file,"
    which is different from a present-but-blank cell (still a key, value
    is blank/None).
    """
    values: dict[str, object] = {}
    for field, col_idx in column_index_by_field.items():
        values[field] = row[col_idx] if col_idx < len(row) else None
    return values


def _display_raw(mapped_values: dict[str, object]) -> dict[str, str]:
    return {field: normalize_cell(value) for field, value in mapped_values.items()}


def validate_and_parse_row(row_number: int, mapped_values: dict[str, object]) -> ParsedSaleRow | RejectedRow:
    sale_date = parse_date(mapped_values.get("sale_date"))
    if sale_date is None:
        return RejectedRow(row_number, "missing_date", _display_raw(mapped_values))

    unit_price_val = parse_money(mapped_values["unit_price"]) if "unit_price" in mapped_values else None
    total_amount_val = parse_money(mapped_values["total_amount"]) if "total_amount" in mapped_values else None
    if unit_price_val is None and total_amount_val is None:
        return RejectedRow(row_number, "missing_price", _display_raw(mapped_values))

    quantity = 1
    if "quantity" in mapped_values and normalize_cell(mapped_values["quantity"]) != "":
        parsed_quantity = parse_int(mapped_values["quantity"])
        if parsed_quantity is None:
            return RejectedRow(row_number, "invalid_quantity", _display_raw(mapped_values))
        quantity = parsed_quantity

    mismatch = False
    if unit_price_val is not None:
        final_unit_price = unit_price_val
        if total_amount_val is not None:
            expected = (unit_price_val * quantity).quantize(_CENTS, rounding=ROUND_HALF_UP)
            actual = total_amount_val.quantize(_CENTS, rounding=ROUND_HALF_UP)
            mismatch = abs(expected - actual) > _MISMATCH_TOLERANCE
    else:
        # total_amount_val is guaranteed non-None here (else missing_price above).
        final_unit_price = (total_amount_val / quantity).quantize(_CENTS, rounding=ROUND_HALF_UP)

    cost_price_at_sale = parse_money(mapped_values.get("cost_price_at_sale"))

    product_name = _blank_to_none(mapped_values.get("product_name"))
    sku = _blank_to_none(mapped_values.get("sku"))
    order_reference = _blank_to_none(mapped_values.get("order_reference"))

    return ParsedSaleRow(
        row_number=row_number,
        sale_date=sale_date,
        product_name=product_name,
        sku=sku,
        quantity=quantity,
        unit_price=final_unit_price,
        cost_price_at_sale=cost_price_at_sale,
        order_reference=order_reference,
        total_amount_mismatch=mismatch,
    )


def validate_and_parse_inventory_row(
    row_number: int, mapped_values: dict[str, object]
) -> ParsedInventoryRow | RejectedRow:
    product_name = _blank_to_none(mapped_values.get("product_name"))
    sku = _blank_to_none(mapped_values.get("sku"))
    if not product_name and not sku:
        # Unlike sales (product_id can be None — the sale itself is still a
        # valid revenue fact without it), a row with no identifier here has
        # no reconcilable content at all: it's not a degraded row, it's a
        # non-row.
        return RejectedRow(row_number, "missing_product_identifier", _display_raw(mapped_values))

    quantity_on_hand = parse_int(mapped_values.get("quantity_on_hand"))
    if quantity_on_hand is None:
        # Never defaults, unlike sales' quantity-defaults-to-1 — there's no
        # safe guess for "how much stock is there," and a wrong guess risks
        # a false low-stock signal downstream.
        return RejectedRow(row_number, "missing_quantity", _display_raw(mapped_values))
    if quantity_on_hand < 0:
        # Parses cleanly but is nonsensical for this field — a negative
        # count isn't "garbled," it's a different failure that "blank vs.
        # unparseable" alone wouldn't catch.
        return RejectedRow(row_number, "negative_quantity", _display_raw(mapped_values))

    return ParsedInventoryRow(
        row_number=row_number, product_name=product_name, sku=sku, quantity_on_hand=quantity_on_hand
    )


def validate_and_parse_purchase_row(
    row_number: int, mapped_values: dict[str, object]
) -> ParsedPurchaseRow | RejectedRow:
    purchase_date = parse_date(mapped_values.get("purchase_date"))
    if purchase_date is None:
        return RejectedRow(row_number, "missing_date", _display_raw(mapped_values))

    product_name = _blank_to_none(mapped_values.get("product_name"))
    sku = _blank_to_none(mapped_values.get("sku"))
    if not product_name and not sku:
        return RejectedRow(row_number, "missing_product_identifier", _display_raw(mapped_values))

    quantity_received = parse_int(mapped_values.get("quantity_received"))
    if quantity_received is None:
        return RejectedRow(row_number, "missing_quantity", _display_raw(mapped_values))
    if quantity_received <= 0:
        # A non-positive receipt isn't a purchase fact — that's a "return",
        # a different reason (reserved on InventoryMovement, not written by
        # this entity type). Distinct code from sales' "invalid_quantity"
        # (which means unparseable, not merely non-positive) — this one
        # parsed fine, it's just semantically wrong for this field.
        return RejectedRow(row_number, "non_positive_quantity", _display_raw(mapped_values))

    unit_cost = parse_money(mapped_values.get("unit_cost"))

    return ParsedPurchaseRow(
        row_number=row_number,
        purchase_date=purchase_date,
        product_name=product_name,
        sku=sku,
        quantity_received=quantity_received,
        unit_cost=unit_cost,
    )


def validate_and_parse_repair_row(
    row_number: int, mapped_values: dict[str, object]
) -> ParsedRepairRow | RejectedRow:
    repair_date = parse_date(mapped_values.get("repair_date"))
    if repair_date is None:
        return RejectedRow(row_number, "missing_date", _display_raw(mapped_values))

    description = _blank_to_none(mapped_values.get("description"))
    price_charged = parse_money(mapped_values.get("price_charged"))
    labour_cost = parse_money(mapped_values.get("labour_cost"))
    if description is None and price_charged is None and labour_cost is None:
        # A bare date with nothing else carries no usable content.
        return RejectedRow(row_number, "missing_repair_detail", _display_raw(mapped_values))

    return ParsedRepairRow(
        row_number=row_number,
        repair_date=repair_date,
        description=description,
        price_charged=price_charged,
        labour_cost=labour_cost,
    )


def _blank_to_none(value: object) -> str | None:
    display = normalize_cell(value)
    return display if display else None


def group_rows_into_sales(rows: list[ParsedSaleRow]) -> list[list[ParsedSaleRow]]:
    """Groups rows sharing a non-blank order_reference (within this import
    call only) into one multi-item sale; a blank/absent reference makes a
    row its own singleton sale. File order is preserved.
    """
    groups: list[list[ParsedSaleRow]] = []
    group_by_ref: dict[str, list[ParsedSaleRow]] = {}
    for row in rows:
        ref = _normalize_order_reference(row.order_reference)
        if ref is None:
            groups.append([row])
            continue
        if ref not in group_by_ref:
            new_group: list[ParsedSaleRow] = []
            group_by_ref[ref] = new_group
            groups.append(new_group)
        group_by_ref[ref].append(row)
    return groups


def _normalize_order_reference(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", value.strip())
    return collapsed or None


def group_total_amount(rows: list[ParsedSaleRow]) -> Decimal:
    return sum((r.unit_price * r.quantity for r in rows), start=Decimal("0")).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )


def group_sold_at(rows: list[ParsedSaleRow]) -> date:
    return min(r.sale_date for r in rows)


# --- Product matching -------------------------------------------------
#
# Deliberately not reusing app/imports/aliases.py's normalize_header: that
# collapses "-"/"_"/"." to spaces, which is wrong for SKUs like "AB-123".

_SKU_WHITESPACE_RE = re.compile(r"\s+")


def normalize_sku(sku: str) -> str:
    return _SKU_WHITESPACE_RE.sub(" ", sku.strip()).upper()


def normalize_product_name(name: str) -> str:
    return _SKU_WHITESPACE_RE.sub(" ", name.strip()).lower()


@dataclass
class ProductMatch:
    action: str  # "existing" | "create" | "none"
    product_id: uuid.UUID | None = None
    create_sku: str | None = None
    create_name: str | None = None
    name_mismatch: bool = False


class ProductMatcher:
    """Pure in-memory SKU/name matching — no DB access. Seed once per
    import from every existing Product for the business; call resolve()
    per row; call register_created() after actually inserting a new
    Product so later rows in the same file resolve to it too.

    SKU is matched on its own, never falling back to a name match when the
    SKU doesn't hit — trusting a name guess after the reliable identifier
    misses risks silently merging two distinct products' sales history,
    which is unrecoverable. An occasional duplicate product from a near-
    miss is a far safer failure mode.
    """

    def __init__(self, existing_products) -> None:
        self._by_sku: dict[str, object] = {}
        self._by_name: dict[str, object] = {}
        for product in existing_products:
            if product.sku:
                self._by_sku[normalize_sku(product.sku)] = product
            self._by_name[normalize_product_name(product.name)] = product

    def resolve(self, *, sku: str | None, product_name: str | None) -> ProductMatch:
        if sku:
            key = normalize_sku(sku)
            existing = self._by_sku.get(key)
            if existing is not None:
                mismatch = bool(product_name) and normalize_product_name(existing.name) != normalize_product_name(
                    product_name
                )
                return ProductMatch(action="existing", product_id=existing.id, name_mismatch=mismatch)
            return ProductMatch(action="create", create_sku=sku, create_name=product_name or sku)

        if product_name:
            key = normalize_product_name(product_name)
            existing = self._by_name.get(key)
            if existing is not None:
                return ProductMatch(action="existing", product_id=existing.id)
            return ProductMatch(action="create", create_sku=None, create_name=product_name)

        return ProductMatch(action="none")

    def register_created(self, product) -> None:
        if product.sku:
            self._by_sku[normalize_sku(product.sku)] = product
        self._by_name[normalize_product_name(product.name)] = product


# --- Inventory reconciliation (pure, no DB) ------------------------------
#
# An inventory upload is a snapshot, not a transaction — it never creates
# Sale/SaleItem rows. Per product: delta = uploaded_qty - current_derived_
# stock, written as one "adjustment" InventoryMovement if non-zero. This
# keeps "stock is derived, never stored directly" intact by treating the
# upload as a reconciliation event, not an overwrite.


@dataclass
class ResolvedInventoryRow:
    row_number: int
    product_id: uuid.UUID
    quantity_on_hand: int
    is_new_product: bool  # new product => starting stock is 0 by definition


@dataclass
class InventoryWriteResult:
    row_number: int
    product_id: uuid.UUID
    delta: int  # 0 means no movement needed (already matches)


def reconcile_inventory_rows(
    resolved_rows: list[ResolvedInventoryRow], starting_stock: dict[uuid.UUID, int]
) -> tuple[list[InventoryWriteResult], list[dict]]:
    """Computes each row's adjustment delta in file order. `starting_stock`
    is read, never mutated (a local running copy tracks each product's
    stock as rows are processed) — necessary because the same product can
    legitimately appear twice in one file: a read-only snapshot would have
    both rows compute delta against the same stale total instead of
    compounding, silently under- or over-adjusting. Returns write results
    plus a list of {"row_number"} entries for any product seen more than
    once in this file (surfaced as a warning, not hidden as "last wins").
    """
    running = dict(starting_stock)
    results: list[InventoryWriteResult] = []
    duplicate_rows: list[dict] = []
    seen: set[uuid.UUID] = set()
    for row in resolved_rows:
        current = 0 if row.is_new_product else running.get(row.product_id, 0)
        if row.product_id in seen:
            duplicate_rows.append({"row_number": row.row_number})
        seen.add(row.product_id)
        delta = row.quantity_on_hand - current
        results.append(InventoryWriteResult(row.row_number, row.product_id, delta))
        running[row.product_id] = row.quantity_on_hand
    return results, duplicate_rows


# --- Rejection/warning summary (PR-2.8/2.9) ----------------------------

_REJECTION_MESSAGE_TEMPLATES = {
    "missing_date": "no date found",
    "missing_price": "no price found",
    "invalid_quantity": "quantity couldn't be read",
    "missing_product_identifier": "no product name or SKU found",
    "missing_quantity": "no stock count found",
    "negative_quantity": "stock count can't be negative",
    "missing_repair_detail": "no description, price, or labour cost found",
    "non_positive_quantity": "quantity received must be greater than zero",
}
_WARNING_MESSAGE_TEMPLATES = {
    "product_name_mismatch": "product name didn't match its existing SKU record — kept the existing name",
    "total_amount_mismatch": "had a total that didn't match price × quantity — used price × quantity",
    "duplicate_product_in_file": "the same product appeared more than once — used the last value",
}


def _build_rejection_summary(
    rejections: list[RejectedRow], warnings: dict[str, list[dict]]
) -> dict | None:
    if not rejections and not warnings:
        return None
    summary: dict = {}
    if rejections:
        grouped: dict[str, list[RejectedRow]] = defaultdict(list)
        for r in rejections:
            grouped[r.code].append(r)
        summary["reasons"] = {
            code: {
                "count": len(items),
                "message": f"{len(items)} rows skipped: {_REJECTION_MESSAGE_TEMPLATES[code]}",
                "sample_rows": [{"row_number": r.row_number, "raw": r.raw} for r in items[:_SAMPLE_CAP]],
            }
            for code, items in grouped.items()
        }
    if warnings:
        summary["warnings"] = {
            code: {
                "count": len(items),
                "message": f"{len(items)} row(s) {_WARNING_MESSAGE_TEMPLATES[code]}",
                "sample_rows": items[:_SAMPLE_CAP],
            }
            for code, items in warnings.items()
            if items
        }
    return summary


# --- Orchestration (DB + file I/O) --------------------------------------


@dataclass
class ImportResult:
    import_record_id: uuid.UUID
    status: str
    rows_total: int
    rows_imported: int
    rows_rejected: int
    rejection_summary: dict | None = None


def _write_sales(
    db: Session, upload: Upload, import_record: ImportRecord, parsed_rows: list[ParsedSaleRow]
) -> tuple[int, dict[str, list[dict]], set[uuid.UUID]]:
    warnings: dict[str, list[dict]] = defaultdict(list)
    for row in parsed_rows:
        if row.total_amount_mismatch:
            warnings["total_amount_mismatch"].append({"row_number": row.row_number})

    product_repo = ProductRepository(db)
    sale_repo = SaleRepository(db)
    sale_item_repo = SaleItemRepository(db)
    movement_repo = InventoryMovementRepository(db)

    matcher = ProductMatcher(product_repo.list_for_business(upload.business_id))

    rows_imported = 0
    touched_product_ids: set[uuid.UUID] = set()
    for group in group_rows_into_sales(parsed_rows):
        sale = sale_repo.create(
            business_id=upload.business_id,
            sold_at=datetime.combine(group_sold_at(group), datetime.min.time(), tzinfo=timezone.utc),
            total_amount=group_total_amount(group),
            order_reference=group[0].order_reference,
            import_record_id=import_record.id,
        )
        for row in group:
            match = matcher.resolve(sku=row.sku, product_name=row.product_name)
            product_id = None
            if match.action == "create":
                product = product_repo.create(
                    business_id=upload.business_id,
                    sku=match.create_sku,
                    name=match.create_name,
                    cost_price=row.cost_price_at_sale,
                    sell_price=row.unit_price,
                )
                matcher.register_created(product)
                product_id = product.id
            elif match.action == "existing":
                product_id = match.product_id
                if match.name_mismatch:
                    warnings["product_name_mismatch"].append(
                        {"row_number": row.row_number, "product_name": row.product_name}
                    )

            item = sale_item_repo.create(
                business_id=upload.business_id,
                sale_id=sale.id,
                product_id=product_id,
                quantity=row.quantity,
                unit_price=row.unit_price,
                cost_price_at_sale=row.cost_price_at_sale,
            )
            if product_id is not None:
                movement_repo.create(
                    business_id=upload.business_id,
                    product_id=product_id,
                    quantity_delta=-row.quantity,
                    reason="sale",
                    reference_id=item.id,
                )
                touched_product_ids.add(product_id)
            rows_imported += 1
    return rows_imported, warnings, touched_product_ids


def _write_inventory(
    db: Session, upload: Upload, import_record: ImportRecord, parsed_rows: list[ParsedInventoryRow]
) -> tuple[int, dict[str, list[dict]], set[uuid.UUID]]:
    warnings: dict[str, list[dict]] = defaultdict(list)
    product_repo = ProductRepository(db)
    movement_repo = InventoryMovementRepository(db)
    matcher = ProductMatcher(product_repo.list_for_business(upload.business_id))

    # Pass 1: resolve every row to a product, creating as needed — mirrors
    # _write_sales' matching exactly (same matcher, same reused-as-is class).
    resolved: list[ResolvedInventoryRow] = []
    for row in parsed_rows:
        match = matcher.resolve(sku=row.sku, product_name=row.product_name)
        if match.action == "create":
            product = product_repo.create(
                business_id=upload.business_id,
                sku=match.create_sku,
                name=match.create_name,
                cost_price=None,
                sell_price=None,
            )
            matcher.register_created(product)
            resolved.append(
                ResolvedInventoryRow(row.row_number, product.id, row.quantity_on_hand, is_new_product=True)
            )
        else:
            # Never "none" here — validate_and_parse_inventory_row already
            # rejects rows with no sku and no product_name before this point.
            if match.name_mismatch:
                warnings["product_name_mismatch"].append(
                    {"row_number": row.row_number, "product_name": row.product_name}
                )
            resolved.append(
                ResolvedInventoryRow(row.row_number, match.product_id, row.quantity_on_hand, is_new_product=False)
            )

    existing_ids = [r.product_id for r in resolved if not r.is_new_product]
    starting_stock = movement_repo.sum_by_product_ids(upload.business_id, existing_ids)

    write_results, duplicate_rows = reconcile_inventory_rows(resolved, starting_stock)
    if duplicate_rows:
        warnings["duplicate_product_in_file"].extend(duplicate_rows)

    rows_imported = 0
    touched_product_ids: set[uuid.UUID] = set()
    for result in write_results:
        if result.delta != 0:
            movement_repo.create(
                business_id=upload.business_id,
                product_id=result.product_id,
                quantity_delta=result.delta,
                reason="adjustment",
                import_record_id=import_record.id,
            )
            touched_product_ids.add(result.product_id)
        rows_imported += 1
    return rows_imported, warnings, touched_product_ids


def _write_purchases(
    db: Session, upload: Upload, import_record: ImportRecord, parsed_rows: list[ParsedPurchaseRow]
) -> tuple[int, dict[str, list[dict]], set[uuid.UUID]]:
    warnings: dict[str, list[dict]] = defaultdict(list)
    product_repo = ProductRepository(db)
    movement_repo = InventoryMovementRepository(db)
    matcher = ProductMatcher(product_repo.list_for_business(upload.business_id))

    rows_imported = 0
    touched_product_ids: set[uuid.UUID] = set()
    cost_updated_products: set[uuid.UUID] = set()
    for row in parsed_rows:
        match = matcher.resolve(sku=row.sku, product_name=row.product_name)
        if match.action == "create":
            product = product_repo.create(
                business_id=upload.business_id,
                sku=match.create_sku,
                name=match.create_name,
                cost_price=row.unit_cost,
                sell_price=None,
            )
            matcher.register_created(product)
            product_id = product.id
        else:
            # Never "none" here — validate_and_parse_purchase_row already
            # rejects rows with no sku and no product_name before this point.
            product_id = match.product_id
            if match.name_mismatch:
                warnings["product_name_mismatch"].append(
                    {"row_number": row.row_number, "product_name": row.product_name}
                )
            if row.unit_cost is not None:
                if product_id in cost_updated_products:
                    warnings["duplicate_product_in_file"].append({"row_number": row.row_number})
                product_repo.update_cost_price(
                    business_id=upload.business_id, product_id=product_id, cost_price=row.unit_cost
                )
                cost_updated_products.add(product_id)

        movement_repo.create(
            business_id=upload.business_id,
            product_id=product_id,
            quantity_delta=row.quantity_received,
            reason="purchase",
            import_record_id=import_record.id,
        )
        touched_product_ids.add(product_id)
        rows_imported += 1
    return rows_imported, warnings, touched_product_ids


def _write_repairs(
    db: Session, upload: Upload, import_record: ImportRecord, parsed_rows: list[ParsedRepairRow]
) -> tuple[int, dict[str, list[dict]], set[uuid.UUID]]:
    event_repo = ProductionEventRepository(db)
    rows_imported = 0
    for row in parsed_rows:
        # These are historical, already-finished jobs from an export, not
        # live in-progress repairs — status="completed" (not the model's
        # "open" default, reserved for a possible future real-time entry
        # screen), completed_at set to the same date since a periodic
        # export has no separate "opened" timestamp to offer.
        opened_at = datetime.combine(row.repair_date, datetime.min.time(), tzinfo=timezone.utc)
        event_repo.create(
            business_id=upload.business_id,
            event_type="repair",
            description=row.description,
            status="completed",
            opened_at=opened_at,
            completed_at=opened_at,
            labour_cost=row.labour_cost,
            price_charged=row.price_charged,
            customer_id=None,
            performed_by_id=None,
            import_record_id=import_record.id,
        )
        rows_imported += 1
    # No InventoryMovement written (v1 has no parts-consumed detail), so
    # nothing for refresh_low_stock_alerts to do — an empty set is a
    # correct, cheap no-op there.
    return rows_imported, {}, set()


def run_import(db: Session, upload: Upload, import_record: ImportRecord) -> ImportResult:
    if upload.status != "mapped" or import_record.status != "mapped":
        raise ImportRecordNotReady(import_record.status)

    profile = ImportMappingProfileRepository(db).get_by_id(upload.business_id, import_record.mapping_profile_id)
    field_mapping: dict[str, str | None] = profile.column_mapping["fields"]

    file_bytes = download_checked(upload.storage_key)
    grid = file_parser.read_rows(file_bytes, upload.original_filename, max_rows=_MAX_IMPORT_ROWS)
    try:
        header_row_index = detection.detect_header_row(grid, upload.entity_type)
    except HeaderRowNotFound:
        # Falls back to the index confirmed at mapping time, stored
        # specifically for this case — a file whose header auto-detection
        # never succeeds (that's why it needed a manual pick in the first
        # place) would otherwise fail here identically, every time.
        stored_index = profile.column_mapping.get("header_row_index")
        if stored_index is None:
            raise
        header_row_index = stored_index
    columns = [normalize_cell(c) for c in grid[header_row_index]]
    data_rows = grid[header_row_index + 1 :]

    column_index_by_field: dict[str, int] = {}
    for field, source_column in field_mapping.items():
        if source_column is None:
            continue
        try:
            column_index_by_field[field] = columns.index(source_column)
        except ValueError:
            raise MappedColumnMissing(source_column)

    parse_row = _PARSE_ROW_FNS[upload.entity_type]

    parsed_rows: list[ParsedSaleRow | ParsedInventoryRow | ParsedPurchaseRow | ParsedRepairRow] = []
    rejections: list[RejectedRow] = []
    for offset, row in enumerate(data_rows):
        if not any(normalize_cell(c) != "" for c in row):
            continue  # fully blank row — not data, not counted as a rejection either
        row_number = header_row_index + 2 + offset  # 1-indexed, spreadsheet-visible
        mapped_values = extract_mapped_values(row, column_index_by_field)
        result = parse_row(row_number, mapped_values)
        if isinstance(result, RejectedRow):
            rejections.append(result)
        else:
            parsed_rows.append(result)

    rows_imported, warnings, touched_product_ids = _WRITE_FNS[upload.entity_type](
        db, upload, import_record, parsed_rows
    )

    rejection_summary = _build_rejection_summary(rejections, warnings)
    rows_total = rows_imported + len(rejections)

    ImportRecordRepository(db).update_after_import(
        import_record,
        status="completed",
        rows_total=rows_total,
        rows_imported=rows_imported,
        rows_rejected=len(rejections),
        rejection_summary=rejection_summary,
    )
    UploadRepository(db).set_status_flush_only(upload, status="imported")

    # The single all-or-nothing point. app/api/deps.py's get_db uses
    # `with SessionLocal() as session`, whose close() on an uncommitted
    # exception implicitly rolls back everything above — no manual
    # try/rollback needed on the happy or error paths.
    db.commit()

    # Only after the commit succeeds (ADR-008/PR-2.10): commit-then-delete,
    # not the reverse — a failed delete just leaves a harmless stale R2
    # object, whereas deleting first and having the commit fail would
    # destroy the source file *and* the import together.
    try:
        r2_client_module.delete_object(storage_key=upload.storage_key)
    except Exception:
        logger.exception("Failed to delete R2 object after successful import: %s", upload.storage_key)

    # Stage C12 (PD-009/PR-9.1): fire low-stock alerts for whatever this
    # import actually touched. Same "only after the main commit succeeds,
    # never let a failure here undo or block a successful import" reasoning
    # as the R2 cleanup right above — refresh_low_stock_alerts owns its own
    # commit, so a failure here can't roll back the import that already
    # committed.
    try:
        refresh_low_stock_alerts(db, business_id=upload.business_id, product_ids=touched_product_ids)
    except Exception:
        logger.exception("Failed to refresh low-stock alerts after import for business: %s", upload.business_id)

    return ImportResult(
        import_record_id=import_record.id,
        status="completed",
        rows_total=rows_total,
        rows_imported=rows_imported,
        rows_rejected=len(rejections),
        rejection_summary=rejection_summary,
    )


def undo_import(db: Session, import_record: ImportRecord) -> ImportRecord:
    if import_record.status != "completed" or import_record.reversed_at is not None:
        raise ImportNotReversible(import_record.status, import_record.reversed_at)

    # A sales/purchase movement's magnitude (-quantity / +quantity_received)
    # is independent of everything else in the ledger, so undoing one has
    # always been safe unconditionally. An adjustment movement's magnitude
    # is NOT independent — it's uploaded_qty minus stock-at-the-moment-it-
    # ran, which bakes in every movement before it. Undoing anything that
    # writes InventoryMovement rows (sales, inventory, purchases) and ran
    # before a later, still-in-effect inventory reconciliation would
    # silently corrupt the stock that reconciliation established. Checked
    # globally, before the entity-type branch below, because this can
    # corrupt a *sales* or *purchases* undo too, not just an inventory one.
    #
    # "repairs" is deliberately exempt: it writes zero InventoryMovement
    # rows (v1 has no parts-consumed detail), so it can never be affected by
    # or corrupt a later inventory reconciliation — the guard would be a
    # pure, incorrect false-positive block for it, not a safety margin.
    if import_record.entity_type != "repairs" and ImportRecordRepository(db).has_later_completed_inventory_import(
        import_record.business_id, after=import_record.updated_at
    ):
        raise ImportSupersededByLaterInventoryImport()

    touched_product_ids = _UNDO_FNS[import_record.entity_type](db, import_record)

    ImportRecordRepository(db).mark_reversed(import_record, reversed_at=datetime.now(timezone.utc))
    db.commit()

    # Stage C12 (PD-009/PR-9.1): undoing an import changes stock too (a
    # sale reversal restores it, an adjustment reversal reverts it) — same
    # "after the real commit, never let a failure here undo a successful
    # undo" reasoning as run_import's own refresh call.
    try:
        refresh_low_stock_alerts(db, business_id=import_record.business_id, product_ids=touched_product_ids)
    except Exception:
        logger.exception("Failed to refresh low-stock alerts after undo for business: %s", import_record.business_id)

    return import_record


def _undo_sales_import(db: Session, import_record: ImportRecord) -> set[uuid.UUID]:
    sale_repo = SaleRepository(db)
    sale_item_repo = SaleItemRepository(db)
    movement_repo = InventoryMovementRepository(db)

    sale_ids = sale_repo.list_ids_by_import_record(import_record.business_id, import_record.id)
    sale_item_ids = sale_item_repo.list_ids_by_sale_ids(sale_ids)
    touched_product_ids = sale_item_repo.list_product_ids_by_sale_ids(sale_ids)

    # FK-dependency order, explicit bulk deletes rather than relying on
    # cascade — the test suite runs SQLite, which doesn't enforce FKs by
    # default, so explicit ordering is what's actually portable.
    movement_repo.bulk_delete_by_reference_ids(sale_item_ids)
    sale_item_repo.bulk_delete_by_sale_ids(sale_ids)
    sale_repo.bulk_delete_by_ids(sale_ids)

    # Products this import may have auto-created are deliberately left in
    # place — proving "no other references anywhere" needs a cross-import
    # scan, and the user may have already edited that product since.

    return touched_product_ids


def _undo_movement_import(db: Session, import_record: ImportRecord) -> set[uuid.UUID]:
    """Shared by "inventory" and "purchases" — both write nothing but
    InventoryMovement rows traced directly by import_record_id (reference_id
    is sales-only), so undoing either is the same operation: bulk-delete by
    import_record_id. Products left in place, same reasoning as the sales
    path. (Named for what it does, not either entity type specifically —
    was _undo_inventory_import before "purchases" needed the identical body.)
    """
    movement_repo = InventoryMovementRepository(db)
    touched_product_ids = movement_repo.list_product_ids_by_import_record_id(
        import_record.business_id, import_record.id
    )
    movement_repo.bulk_delete_by_import_record_id(import_record.business_id, import_record.id)
    return touched_product_ids


def _undo_repairs_import(db: Session, import_record: ImportRecord) -> set[uuid.UUID]:
    event_repo = ProductionEventRepository(db)
    event_ids = event_repo.list_ids_by_import_record(import_record.business_id, import_record.id)
    event_repo.bulk_delete_by_ids(event_ids)
    # No InventoryMovement ever written by a repairs import — nothing for
    # refresh_low_stock_alerts to do.
    return set()


# Dispatch tables — one binary if/else per concern outgrew itself once a
# third and fourth entity type arrived. Pure refactor for "sales"/
# "inventory": same functions, same behavior, so no existing test needed to
# change for those two.
_PARSE_ROW_FNS = {
    "sales": validate_and_parse_row,
    "inventory": validate_and_parse_inventory_row,
    "purchases": validate_and_parse_purchase_row,
    "repairs": validate_and_parse_repair_row,
}

_WRITE_FNS = {
    "sales": _write_sales,
    "inventory": _write_inventory,
    "purchases": _write_purchases,
    "repairs": _write_repairs,
}

_UNDO_FNS = {
    "sales": _undo_sales_import,
    "inventory": _undo_movement_import,
    "purchases": _undo_movement_import,
    "repairs": _undo_repairs_import,
}
