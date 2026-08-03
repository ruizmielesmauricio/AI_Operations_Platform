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
    MappedColumnMissing,
)
from app.imports.file_parser import normalize_cell
from app.imports.service import download_checked
from app.imports.value_parsers import parse_date, parse_int, parse_money
from app.models.import_record import ImportRecord
from app.models.upload import Upload
from app.repositories.import_mapping_profile import ImportMappingProfileRepository
from app.repositories.import_record import ImportRecordRepository
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductRepository
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
class RejectedRow:
    row_number: int
    code: str  # "missing_date" | "missing_price" | "invalid_quantity"
    raw: dict[str, str]


_REJECTION_MESSAGES = {
    "missing_date": "no date found",
    "missing_price": "no price found",
    "invalid_quantity": "quantity couldn't be read",
}


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


# --- Rejection/warning summary (PR-2.8/2.9) ----------------------------

_REJECTION_MESSAGE_TEMPLATES = {
    "missing_date": "no date found",
    "missing_price": "no price found",
    "invalid_quantity": "quantity couldn't be read",
}
_WARNING_MESSAGE_TEMPLATES = {
    "product_name_mismatch": "product name didn't match its existing SKU record — kept the existing name",
    "total_amount_mismatch": "had a total that didn't match price × quantity — used price × quantity",
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

    parsed_rows: list[ParsedSaleRow] = []
    rejections: list[RejectedRow] = []
    for offset, row in enumerate(data_rows):
        if not any(normalize_cell(c) != "" for c in row):
            continue  # fully blank row — not data, not counted as a rejection either
        row_number = header_row_index + 2 + offset  # 1-indexed, spreadsheet-visible
        mapped_values = extract_mapped_values(row, column_index_by_field)
        result = validate_and_parse_row(row_number, mapped_values)
        if isinstance(result, RejectedRow):
            rejections.append(result)
        else:
            parsed_rows.append(result)

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
            rows_imported += 1

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

    sale_repo = SaleRepository(db)
    sale_item_repo = SaleItemRepository(db)
    movement_repo = InventoryMovementRepository(db)

    sale_ids = sale_repo.list_ids_by_import_record(import_record.business_id, import_record.id)
    sale_item_ids = sale_item_repo.list_ids_by_sale_ids(sale_ids)

    # FK-dependency order, explicit bulk deletes rather than relying on
    # cascade — the test suite runs SQLite, which doesn't enforce FKs by
    # default, so explicit ordering is what's actually portable.
    movement_repo.bulk_delete_by_reference_ids(sale_item_ids)
    sale_item_repo.bulk_delete_by_sale_ids(sale_ids)
    sale_repo.bulk_delete_by_ids(sale_ids)

    # Products this import may have auto-created are deliberately left in
    # place — proving "no other references anywhere" needs a cross-import
    # scan, and the user may have already edited that product since.

    ImportRecordRepository(db).mark_reversed(import_record, reversed_at=datetime.now(timezone.utc))
    db.commit()
    return import_record
