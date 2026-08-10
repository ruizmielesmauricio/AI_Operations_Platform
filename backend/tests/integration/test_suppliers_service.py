"""Application-layer tests for supplier CRUD/merge/manual-correction and
the spend analytics surface (Gap 4) — see tests/unit/test_replenishment.py
for the pure recommendation formula, and
tests/tenant_isolation/test_suppliers_isolation.py for the HTTP-level
role/cross-tenant boundary.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.application.suppliers import (
    CannotMergeSupplierIntoItself,
    ProductNotFound,
    SupplierNotFound,
    correct_product_supplier,
    create_supplier,
    deactivate_supplier,
    get_supplier_analytics,
    list_suppliers,
    merge_suppliers,
    update_supplier,
)
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.repositories.supplier import SupplierRepository


def _make_product(db_session, business_id, name="Chain Lube"):
    product = Product(business_id=business_id, name=name, sku=None, cost_price=None, sell_price=None)
    db_session.add(product)
    db_session.commit()
    return product


def test_create_supplier_creates_a_new_row(db_session, business_id):
    supplier, created = create_supplier(
        db_session, business_id=business_id, name="Acme Parts Ltd", contact_info="acme@example.com",
        creating_user_id="user-a",
    )
    assert created is True
    assert supplier.name == "Acme Parts Ltd"
    assert supplier.status == "active"


def test_create_supplier_matches_an_existing_active_supplier_by_normalized_name(db_session, business_id):
    first, _ = create_supplier(db_session, business_id=business_id, name="Acme Parts", contact_info=None, creating_user_id="user-a")
    second, created = create_supplier(
        db_session, business_id=business_id, name="  acme   parts  ", contact_info=None, creating_user_id="user-a"
    )
    assert created is False
    assert second.id == first.id
    assert len(list_suppliers(db_session, business_id)) == 1


def test_update_supplier_renames_and_updates_normalized_name(db_session, business_id):
    supplier, _ = create_supplier(db_session, business_id=business_id, name="Old Name", contact_info=None, creating_user_id="u")
    updated = update_supplier(
        db_session, business_id=business_id, supplier_id=supplier.id, name="New Name", contact_info="x@example.com",
        editing_user_id="u",
    )
    assert updated.name == "New Name"
    assert updated.normalized_name == "new name"
    assert updated.contact_info == "x@example.com"


def test_update_nonexistent_supplier_raises(db_session, business_id):
    with pytest.raises(SupplierNotFound):
        update_supplier(
            db_session, business_id=business_id, supplier_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            name="x", contact_info=None, editing_user_id="u",
        )


def test_deactivate_supplier_is_idempotent(db_session, business_id):
    supplier, _ = create_supplier(db_session, business_id=business_id, name="Gone Ltd", contact_info=None, creating_user_id="u")
    first = deactivate_supplier(db_session, business_id=business_id, supplier_id=supplier.id, deleting_user_id="u")
    second = deactivate_supplier(db_session, business_id=business_id, supplier_id=supplier.id, deleting_user_id="u")
    assert first.status == "deleted"
    assert second.status == "deleted"
    assert supplier.id not in [s.id for s in list_suppliers(db_session, business_id)]


def test_merge_reassigns_inventory_movements_and_product_links(db_session, business_id):
    product = _make_product(db_session, business_id)
    source, _ = create_supplier(db_session, business_id=business_id, name="Source Co", contact_info=None, creating_user_id="u")
    target, _ = create_supplier(db_session, business_id=business_id, name="Target Co", contact_info=None, creating_user_id="u")

    db_session.add(
        InventoryMovement(
            business_id=business_id, product_id=product.id, quantity_delta=5, reason="purchase",
            event_date=date(2026, 1, 5), unit_cost=Decimal("2.00"), supplier_id=source.id,
        )
    )
    db_session.commit()
    correct_product_supplier(
        db_session, business_id=business_id, product_id=product.id, supplier_id=source.id,
        supplier_sku="SRC-1", lead_time_days=Decimal("5"), editing_user_id="u",
    )

    merged_target = merge_suppliers(
        db_session, business_id=business_id, source_id=source.id, target_id=target.id, merging_user_id="u"
    )
    assert merged_target.id == target.id

    refreshed_source = SupplierRepository(db_session).get_for_business(business_id, source.id)
    assert refreshed_source.status == "merged"
    assert refreshed_source.merged_into_id == target.id

    movement = db_session.query(InventoryMovement).filter_by(business_id=business_id).one()
    assert movement.supplier_id == target.id

    links = SupplierRepository(db_session).list_links_for_product(business_id, product.id)
    assert len(links) == 1
    assert links[0].supplier_id == target.id
    assert links[0].lead_time_days == Decimal("5")


def test_merge_into_itself_is_rejected(db_session, business_id):
    supplier, _ = create_supplier(db_session, business_id=business_id, name="Solo Co", contact_info=None, creating_user_id="u")
    with pytest.raises(CannotMergeSupplierIntoItself):
        merge_suppliers(db_session, business_id=business_id, source_id=supplier.id, target_id=supplier.id, merging_user_id="u")


def test_merge_is_idempotent_when_source_already_merged(db_session, business_id):
    source, _ = create_supplier(db_session, business_id=business_id, name="A", contact_info=None, creating_user_id="u")
    target, _ = create_supplier(db_session, business_id=business_id, name="B", contact_info=None, creating_user_id="u")
    merge_suppliers(db_session, business_id=business_id, source_id=source.id, target_id=target.id, merging_user_id="u")
    # Re-running the same merge must not raise or double-count anything.
    result = merge_suppliers(db_session, business_id=business_id, source_id=source.id, target_id=target.id, merging_user_id="u")
    assert result.id == target.id


def test_correct_product_supplier_sets_lead_time_and_sku(db_session, business_id):
    product = _make_product(db_session, business_id)
    supplier, _ = create_supplier(db_session, business_id=business_id, name="Lead Time Co", contact_info=None, creating_user_id="u")

    link = correct_product_supplier(
        db_session, business_id=business_id, product_id=product.id, supplier_id=supplier.id,
        supplier_sku="ABC-123", lead_time_days=Decimal("14"), editing_user_id="u",
    )
    assert link.supplier_sku == "ABC-123"
    assert link.lead_time_days == Decimal("14")


def test_correct_product_supplier_rejects_a_product_from_another_business(db_session, business_id):
    from app.models.business import Business

    other = Business(name="Other Biz")
    db_session.add(other)
    db_session.commit()
    other_product = _make_product(db_session, other.id, name="Not Yours")
    supplier, _ = create_supplier(db_session, business_id=business_id, name="Co", contact_info=None, creating_user_id="u")

    with pytest.raises(ProductNotFound):
        correct_product_supplier(
            db_session, business_id=business_id, product_id=other_product.id, supplier_id=supplier.id,
            supplier_sku=None, lead_time_days=None, editing_user_id="u",
        )


def test_supplier_analytics_is_deterministic_and_buckets_unknown_supplier(db_session, business_id):
    product = _make_product(db_session, business_id)
    supplier, _ = create_supplier(db_session, business_id=business_id, name="Known Co", contact_info=None, creating_user_id="u")

    db_session.add_all(
        [
            InventoryMovement(
                business_id=business_id, product_id=product.id, quantity_delta=10, reason="purchase",
                event_date=date(2026, 1, 5), unit_cost=Decimal("2.00"), supplier_id=supplier.id,
            ),
            InventoryMovement(
                business_id=business_id, product_id=product.id, quantity_delta=5, reason="purchase",
                event_date=date(2026, 1, 6), unit_cost=Decimal("3.00"), supplier_id=None,
            ),
        ]
    )
    db_session.commit()

    summary = get_supplier_analytics(
        db_session, business_id=business_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
    )
    by_name = {r.supplier_name: r for r in summary.rows}
    assert by_name["Known Co"].spend == Decimal("20.00")  # 10 * 2.00
    assert by_name["Unknown"].spend == Decimal("15.00")  # 5 * 3.00
    assert summary.unknown_supplier_share_pct == Decimal("42.9")  # 15 / 35 * 100

    # Deterministic — same inputs, same output, called again.
    summary2 = get_supplier_analytics(
        db_session, business_id=business_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
    )
    assert summary2.unknown_supplier_share_pct == summary.unknown_supplier_share_pct
