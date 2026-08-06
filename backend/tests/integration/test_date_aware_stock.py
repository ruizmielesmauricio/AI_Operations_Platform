"""Direct repository-level tests for InventoryMovementRepository.
sum_by_product_ids's date-aware calculation — order-independent derived
stock (app/models/inventory_movement.py's event_date/
resulting_quantity_on_hand). Complements the full-pipeline coverage in
tests/integration/test_purchases_repairs_importer.py and
test_inventory_importer.py by exercising the calculation directly against
hand-built movement rows, including scenarios (multiple reconciliations,
an out-of-order backdated one) that would be awkward to set up through
the full import pipeline.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.inventory_movement import InventoryMovementRepository


def _make_product(db_session, business_id, *, name="Chain Lube"):
    product = Product(business_id=business_id, sku=None, name=name, cost_price=Decimal("5.00"), sell_price=Decimal("10.00"))
    db_session.add(product)
    db_session.flush()
    return product


def _make_movement(db_session, business_id, *, product_id, quantity_delta, reason, event_date=None, resulting_quantity_on_hand=None):
    movement = InventoryMovement(
        business_id=business_id,
        product_id=product_id,
        quantity_delta=quantity_delta,
        reason=reason,
        event_date=event_date,
        resulting_quantity_on_hand=resulting_quantity_on_hand,
    )
    db_session.add(movement)
    db_session.flush()
    return movement


def _make_sale_movement(db_session, business_id, *, product_id, quantity, sold_at):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=Decimal(quantity) * Decimal("10.00"), order_reference=None)
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(
        business_id=business_id, sale_id=sale.id, product_id=product_id, quantity=quantity,
        unit_price=Decimal("10.00"), cost_price_at_sale=Decimal("5.00"),
    )
    db_session.add(item)
    db_session.flush()
    _make_movement(
        db_session, business_id, product_id=product_id, quantity_delta=-quantity, reason="sale",
        event_date=sold_at.date(),
    )


def test_no_reconciliation_ever_sums_everything_unconditionally(db_session, business_id):
    # Regression check: a business that's never done a stock count behaves
    # exactly as before this feature — a plain flat sum, no baseline.
    product = _make_product(db_session, business_id)
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=50, reason="purchase", event_date=date(2026, 1, 1))
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=-10, reason="sale", event_date=date(2026, 1, 5))
    db_session.commit()

    stock = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock[product.id] == 40


def test_a_movement_dated_on_or_before_the_reconciliation_is_excluded(db_session, business_id):
    product = _make_product(db_session, business_id)
    # Pre-reconciliation history — irrelevant to the final number once a
    # reconciliation supersedes it.
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=50, reason="purchase", event_date=date(2026, 1, 1))
    # The reconciliation: as of Jan 10, stock is 40 (already accounts for
    # whatever happened before it).
    _make_movement(
        db_session, business_id, product_id=product.id, quantity_delta=-10, reason="adjustment",
        event_date=date(2026, 1, 10), resulting_quantity_on_hand=40,
    )
    # A purchase later PROCESSED but dated Jan 10 (same day — still
    # "on or before", per this system's "final stock of the day" model) —
    # must not be added again.
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=15, reason="purchase", event_date=date(2026, 1, 10))
    db_session.commit()

    stock = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock[product.id] == 40  # not 55 — the same-day purchase is presumed already counted


def test_a_movement_dated_after_the_reconciliation_is_added_on_top(db_session, business_id):
    product = _make_product(db_session, business_id)
    _make_movement(
        db_session, business_id, product_id=product.id, quantity_delta=0, reason="adjustment",
        event_date=date(2026, 1, 10), resulting_quantity_on_hand=40,
    )
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=15, reason="purchase", event_date=date(2026, 1, 11))
    db_session.commit()

    stock = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock[product.id] == 55


def test_only_the_most_recent_of_several_reconciliations_acts_as_the_baseline(db_session, business_id):
    product = _make_product(db_session, business_id)
    _make_movement(
        db_session, business_id, product_id=product.id, quantity_delta=0, reason="adjustment",
        event_date=date(2026, 1, 1), resulting_quantity_on_hand=100,
    )
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=-30, reason="sale", event_date=date(2026, 1, 5))
    _make_movement(
        db_session, business_id, product_id=product.id, quantity_delta=0, reason="adjustment",
        event_date=date(2026, 1, 10), resulting_quantity_on_hand=65,  # the true count — corrects for shrinkage/drift
    )
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=20, reason="purchase", event_date=date(2026, 1, 15))
    db_session.commit()

    stock = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    # 65 (the Jan 10 count, not derived from the Jan 1 one at all) + 20
    # (the only movement dated after it) = 85 — the Jan 1 count and the
    # Jan 5 sale between them play no further role once superseded.
    assert stock[product.id] == 85


def test_an_out_of_order_backdated_reconciliation_is_not_picked_as_the_baseline(db_session, business_id):
    # A historical stock count gets uploaded/processed LAST (wall-clock),
    # but its own date is earlier than one already on file — order of
    # processing must not matter, only the dates themselves.
    product = _make_product(db_session, business_id)
    _make_movement(
        db_session, business_id, product_id=product.id, quantity_delta=0, reason="adjustment",
        event_date=date(2026, 1, 20), resulting_quantity_on_hand=70,
    )
    # Processed after the above, but dated earlier — must be ignored as
    # the baseline in favor of the Jan 20 count.
    _make_movement(
        db_session, business_id, product_id=product.id, quantity_delta=0, reason="adjustment",
        event_date=date(2026, 1, 5), resulting_quantity_on_hand=999,
    )
    db_session.commit()

    stock = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock[product.id] == 70  # not 999 — the later-dated count wins regardless of processing order


def test_a_sale_dated_on_or_before_the_reconciliation_does_not_double_subtract(db_session, business_id):
    # The mirror-image case to purchases: a shop's daily POS export
    # includes both the day's sales and the day's final stock count
    # together — the sale must not be subtracted again on top of a count
    # that already reflects it.
    product = _make_product(db_session, business_id)
    _make_movement(
        db_session, business_id, product_id=product.id, quantity_delta=0, reason="adjustment",
        event_date=date(2026, 1, 10), resulting_quantity_on_hand=40,
    )
    _make_sale_movement(db_session, business_id, product_id=product.id, quantity=3, sold_at=datetime(2026, 1, 10, 18, 0, tzinfo=timezone.utc))
    db_session.commit()

    stock = InventoryMovementRepository(db_session).sum_by_product_ids(business_id, [product.id])
    assert stock[product.id] == 40  # not 37 — the same-day sale is already inside the count
