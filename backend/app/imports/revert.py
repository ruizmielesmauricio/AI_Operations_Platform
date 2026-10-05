"""Puts back what an import overwrote when that import is undone.

An import's "latest value wins" overwrites on EXISTING products (cost price,
sell price, category — see ProductRepository) used to survive undo: delete
the file and its prices stayed behind. Every such overwrite is now recorded
(ProductFieldChange); undo restores the previous value — carefully:

- If the live value is still exactly what this import wrote, restore the
  previous one.
- If a LATER import overwrote it afterwards, don't touch the newer value;
  instead re-point that later change's own "previous value" past this one,
  so undoing it later lands on the true original — never on a value from a
  file that no longer counts.
- If the live value matches neither (someone edited it by hand since),
  leave it alone — undo reverses what a file did, never what a person did.

Products an import CREATED are deliberately still left in place (unchanged
long-standing behaviour — see importer._undo_*), only overwritten values of
pre-existing products are reverted. Flush only: undo_import owns the commit.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.import_record import ImportRecord
from app.models.product import Product
from app.models.product_field_change import ProductFieldChange
from app.repositories.product_field_change import ProductFieldChangeRepository


@dataclass(frozen=True)
class RevertSummary:
    restored: int
    superseded: int
    kept_edited: int


def _normalize(field: str, value: object) -> object:
    if value is None:
        return None
    if field in ("cost_price", "sell_price"):
        return Decimal(str(value))
    return str(value)


def _same(field: str, a: object, b: object) -> bool:
    return _normalize(field, a) == _normalize(field, b)


def _typed(field: str, text: str | None) -> object:
    if text is None:
        return None
    if field in ("cost_price", "sell_price"):
        return Decimal(text)
    return uuid.UUID(text)


def revert_import_overwrites(db: Session, import_record: ImportRecord) -> RevertSummary:
    repo = ProductFieldChangeRepository(db)
    now = datetime.now(timezone.utc)
    restored = superseded = kept_edited = 0

    # Newest first: if one import overwrote the same value twice (a product
    # on two rows of the file), unwind the later write before the earlier,
    # ending on the true original.
    for change in repo.list_for_import_newest_first(import_record.business_id, import_record.id):
        product = db.get(Product, change.product_id)
        if product is None:
            change.status, change.resolved_at = "kept_edited", now
            kept_edited += 1
            continue

        current = getattr(product, change.field)
        if _same(change.field, current, change.new_value):
            setattr(product, change.field, _typed(change.field, change.old_value))
            change.status = "reverted"
            restored += 1
        else:
            # Someone/something moved on. A later import's change whose
            # "previous value" is this one's value gets spliced past it.
            later = next(
                (c for c in repo.later_applied_changes(change) if _same(change.field, c.old_value, change.new_value)),
                None,
            )
            if later is not None:
                later.old_value = change.old_value
                change.status = "superseded"
                superseded += 1
            else:
                change.status = "kept_edited"
                kept_edited += 1
        change.resolved_at = now

    db.flush()
    return RevertSummary(restored=restored, superseded=superseded, kept_edited=kept_edited)
