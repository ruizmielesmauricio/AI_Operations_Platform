"""Application-layer tests for the product/threshold management surface
(Gap 1) — see tests/unit/test_replenishment.py for the pure recommendation
formula and tests/tenant_isolation/test_products_thresholds_isolation.py
for the HTTP-level role/cross-tenant boundary.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.application.products import (
    ProductNotFound,
    list_product_thresholds,
    recalculate_thresholds_after_upload,
    update_product_threshold,
)
from app.models.audit_log import AuditLog
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.supplier import SupplierRepository


def _make_product(db_session, business_id, name="Chain Lube", threshold_days=None):
    product = Product(
        business_id=business_id, name=name, sku=None, cost_price=None, sell_price=None,
        low_stock_threshold_days=threshold_days,
    )
    db_session.add(product)
    db_session.commit()
    return product


def test_product_with_no_sales_history_is_flagged_insufficient_data(db_session, business_id):
    _make_product(db_session, business_id)
    rows = list_product_thresholds(db_session, business_id=business_id)
    assert len(rows) == 1
    assert rows[0].insufficient_data is True
    assert rows[0].units_sold_in_period == 0


def test_product_threshold_falls_back_to_default_without_supplier_lead_time(db_session, business_id):
    _make_product(db_session, business_id)
    rows = list_product_thresholds(db_session, business_id=business_id)
    assert rows[0].recommendation.basis == "default_fallback"
    assert rows[0].effective_threshold_days == Decimal("7")  # global default, no override set


def test_product_threshold_recommendation_uses_supplier_lead_time_when_known(db_session, business_id):
    product = _make_product(db_session, business_id)
    supplier_repo = SupplierRepository(db_session)
    supplier = supplier_repo.create(business_id=business_id, name="Fast Co", contact_info=None)
    supplier_repo.upsert_product_supplier(business_id=business_id, product_id=product.id, supplier_id=supplier.id)
    link = supplier_repo.get_product_supplier(business_id, product_id=product.id, supplier_id=supplier.id)
    link.lead_time_days = Decimal("4")
    db_session.commit()

    rows = list_product_thresholds(db_session, business_id=business_id)
    assert rows[0].recommendation.basis == "supplier_lead_time"
    assert rows[0].recommendation.recommended_threshold_days == Decimal("7.0")  # 4 + 3 buffer


def test_product_threshold_recommendation_unaffected_by_unrelated_supplier_with_no_lead_time(db_session, business_id):
    # A supplier link exists but with no lead_time_days set — must not
    # crash or silently invent a number; falls back to the default same
    # as having no supplier link at all.
    product = _make_product(db_session, business_id)
    supplier_repo = SupplierRepository(db_session)
    supplier = supplier_repo.create(business_id=business_id, name="Unknown Lead Time Co", contact_info=None)
    supplier_repo.upsert_product_supplier(business_id=business_id, product_id=product.id, supplier_id=supplier.id)
    db_session.commit()

    rows = list_product_thresholds(db_session, business_id=business_id)
    assert rows[0].recommendation.basis == "default_fallback"
    assert rows[0].recommendation.lead_time_days is None


def test_update_product_threshold_persists_and_audits_manual_edit(db_session, business_id):
    product = _make_product(db_session, business_id)
    update_product_threshold(
        db_session, business_id=business_id, product_id=product.id, threshold_days=Decimal("12"),
        editing_user_id="user-a",
    )
    refreshed = db_session.get(Product, product.id)
    assert refreshed.low_stock_threshold_days == Decimal("12")

    log = db_session.query(AuditLog).filter_by(business_id=business_id).one()
    assert log.action == "threshold_updated"


def test_accept_recommendation_logs_distinct_audit_action(db_session, business_id):
    product = _make_product(db_session, business_id)
    update_product_threshold(
        db_session, business_id=business_id, product_id=product.id, threshold_days=Decimal("7"),
        editing_user_id="user-a", accepted_recommendation=True,
    )
    log = db_session.query(AuditLog).filter_by(business_id=business_id).one()
    assert log.action == "threshold_recommendation_accepted"


def test_clearing_a_threshold_reverts_to_inherited(db_session, business_id):
    product = _make_product(db_session, business_id, threshold_days=Decimal("20"))
    update_product_threshold(
        db_session, business_id=business_id, product_id=product.id, threshold_days=None, editing_user_id="u",
    )
    rows = list_product_thresholds(db_session, business_id=business_id)
    assert rows[0].product_threshold_days is None
    assert rows[0].effective_threshold_days == Decimal("7")  # global default


def test_update_threshold_for_nonexistent_product_raises(db_session, business_id):
    import uuid

    with pytest.raises(ProductNotFound):
        update_product_threshold(
            db_session, business_id=business_id, product_id=uuid.uuid4(), threshold_days=Decimal("5"),
            editing_user_id="u",
        )


def test_threshold_changes_are_tenant_scoped(db_session, business_id):
    from app.models.business import Business

    other = Business(name="Other Biz")
    db_session.add(other)
    db_session.commit()
    other_product = _make_product(db_session, other.id, name="Not Yours")

    with pytest.raises(ProductNotFound):
        update_product_threshold(
            db_session, business_id=business_id, product_id=other_product.id, threshold_days=Decimal("5"),
            editing_user_id="u",
        )


def test_list_product_thresholds_reflects_actual_stock_and_recent_sales(db_session, business_id):
    product = _make_product(db_session, business_id)
    db_session.add(
        InventoryMovement(
            business_id=business_id, product_id=product.id, quantity_delta=50, reason="purchase",
            event_date=date(2026, 1, 1),
        )
    )
    sale = Sale(business_id=business_id, sold_at=datetime(2026, 1, 15, tzinfo=timezone.utc), total_amount=Decimal("10.00"))
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(business_id=business_id, sale_id=sale.id, product_id=product.id, quantity=3, unit_price=Decimal("10.00"))
    )
    db_session.add(
        InventoryMovement(
            business_id=business_id, product_id=product.id, quantity_delta=-3, reason="sale",
            event_date=date(2026, 1, 15),
        )
    )
    db_session.commit()

    rows = list_product_thresholds(db_session, business_id=business_id)
    assert rows[0].stock_on_hand == 47


# --- Upload-triggered recalculation ---------------------------------------


def _link_supplier_with_lead_time(db_session, business_id, product_id, lead_time_days):
    supplier_repo = SupplierRepository(db_session)
    supplier = supplier_repo.create(business_id=business_id, name="Fast Co", contact_info=None)
    supplier_repo.upsert_product_supplier(business_id=business_id, product_id=product_id, supplier_id=supplier.id)
    link = supplier_repo.get_product_supplier(business_id, product_id=product_id, supplier_id=supplier.id)
    link.lead_time_days = lead_time_days
    db_session.commit()
    return supplier


def test_recalculation_applies_the_recommendation_when_lead_time_is_known(db_session, business_id):
    product = _make_product(db_session, business_id)
    _link_supplier_with_lead_time(db_session, business_id, product.id, Decimal("4"))

    updated_count = recalculate_thresholds_after_upload(
        db_session, business_id=business_id, product_ids={product.id}, triggered_by_user_id="uploader-1"
    )
    assert updated_count == 1

    refreshed = db_session.get(Product, product.id)
    assert refreshed.low_stock_threshold_days == Decimal("7.0")  # 4 + 3 buffer

    log = db_session.query(AuditLog).filter_by(business_id=business_id, action="threshold_recalculation_completed").one()
    assert log.event_metadata["products_updated"] == 1


def test_recalculation_never_overwrites_a_manual_override(db_session, business_id):
    product = _make_product(db_session, business_id, threshold_days=Decimal("99"))
    _link_supplier_with_lead_time(db_session, business_id, product.id, Decimal("4"))

    updated_count = recalculate_thresholds_after_upload(
        db_session, business_id=business_id, product_ids={product.id}, triggered_by_user_id="uploader-1"
    )
    assert updated_count == 0

    refreshed = db_session.get(Product, product.id)
    assert refreshed.low_stock_threshold_days == Decimal("99")  # untouched


def test_recalculation_is_a_no_op_without_known_supplier_lead_time(db_session, business_id):
    # Unknown/missing supplier data must never break recalculation — it's
    # just nothing new to apply, same as any product with no supplier
    # link at all.
    product = _make_product(db_session, business_id)

    updated_count = recalculate_thresholds_after_upload(
        db_session, business_id=business_id, product_ids={product.id}, triggered_by_user_id="uploader-1"
    )
    assert updated_count == 0
    assert db_session.get(Product, product.id).low_stock_threshold_days is None


def test_recalculation_with_no_touched_products_is_a_cheap_no_op(db_session, business_id):
    updated_count = recalculate_thresholds_after_upload(
        db_session, business_id=business_id, product_ids=set(), triggered_by_user_id="uploader-1"
    )
    assert updated_count == 0
    assert db_session.query(AuditLog).filter_by(business_id=business_id).count() == 0


def test_recalculation_is_idempotent(db_session, business_id):
    product = _make_product(db_session, business_id)
    _link_supplier_with_lead_time(db_session, business_id, product.id, Decimal("4"))

    first = recalculate_thresholds_after_upload(
        db_session, business_id=business_id, product_ids={product.id}, triggered_by_user_id="uploader-1"
    )
    second = recalculate_thresholds_after_upload(
        db_session, business_id=business_id, product_ids={product.id}, triggered_by_user_id="uploader-1"
    )
    assert first == 1
    # Once applied, the written value is indistinguishable from a manual
    # override — the second run correctly finds nothing left to do
    # (products_updated == 0) rather than reapplying the same value
    # again. The persisted state is what must stay stable across runs,
    # which it does.
    assert second == 0
    assert db_session.get(Product, product.id).low_stock_threshold_days == Decimal("7.0")


def test_recalculation_is_tenant_scoped(db_session, business_id):
    from app.models.business import Business

    other = Business(name="Other Biz")
    db_session.add(other)
    db_session.commit()
    other_product = _make_product(db_session, other.id, name="Not Yours")
    _link_supplier_with_lead_time(db_session, other.id, other_product.id, Decimal("4"))

    # Passing the wrong business_id for this product's real owner must
    # not touch it — get_for_business's own business_id filter is what
    # protects this, exercised here end-to-end through the recalc path.
    updated_count = recalculate_thresholds_after_upload(
        db_session, business_id=business_id, product_ids={other_product.id}, triggered_by_user_id="u"
    )
    assert updated_count == 0
    assert db_session.get(Product, other_product.id).low_stock_threshold_days is None
