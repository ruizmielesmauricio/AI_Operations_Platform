"""Stage C12 — verifies AlertRepository and app/application/alerts.py's
refresh_low_stock_alerts against a real (SQLite) database: create on first
low reading, update-in-place (not duplicate) on a second, resolve on
recovery, and per-product/category threshold overrides.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.application.alerts import refresh_low_stock_alerts
from app.models.product import Product, ProductCategory
from app.models.sale import Sale, SaleItem
from app.repositories.alert import AlertRepository
from app.repositories.inventory_movement import InventoryMovementRepository


def _make_product(db_session, business_id, *, name, category_id=None, low_stock_threshold_days=None):
    product = Product(
        business_id=business_id,
        sku=None,
        name=name,
        category_id=category_id,
        cost_price=Decimal("5.00"),
        sell_price=Decimal("10.00"),
        low_stock_threshold_days=low_stock_threshold_days,
    )
    db_session.add(product)
    db_session.flush()
    return product


def _make_movement(db_session, business_id, *, product_id, quantity_delta, reason="purchase"):
    InventoryMovementRepository(db_session).create(
        business_id=business_id, product_id=product_id, quantity_delta=quantity_delta, reason=reason
    )


def _make_sale(db_session, business_id, *, product_id, quantity, sold_at):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=Decimal("4.00") * quantity)
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            business_id=business_id,
            sale_id=sale.id,
            product_id=product_id,
            quantity=quantity,
            unit_price=Decimal("4.00"),
            cost_price_at_sale=Decimal("2.00"),
        )
    )
    db_session.flush()


def test_refresh_creates_updates_and_resolves_a_single_alert(db_session, business_id):
    product = _make_product(db_session, business_id, name="Almost Out")
    # Default trailing window is 30 days: stock=5, 25 units sold in the
    # window -> daily rate 0.833/day -> ~6.0 days cover, under the default
    # 7-day threshold.
    _make_sale(db_session, business_id, product_id=product.id, quantity=25, sold_at=datetime.now(timezone.utc))
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=30, reason="purchase")
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=-25, reason="sale")
    db_session.commit()

    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product.id})

    alerts = AlertRepository(db_session).list_active_for_business(business_id)
    assert len(alerts) == 1
    first_alert_id = alerts[0].id
    assert alerts[0].payload["evidence"]["product_id"] == str(product.id)

    # Second low reading (more stock sold, cover drops further) — must
    # update the same row, not create a second one.
    _make_sale(db_session, business_id, product_id=product.id, quantity=3, sold_at=datetime.now(timezone.utc))
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=-3, reason="sale")
    db_session.commit()

    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product.id})

    alerts = AlertRepository(db_session).list_active_for_business(business_id)
    assert len(alerts) == 1
    assert alerts[0].id == first_alert_id  # same row, updated in place

    # Recovery — restock well above the threshold.
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=500, reason="purchase")
    db_session.commit()

    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product.id})

    assert AlertRepository(db_session).list_active_for_business(business_id) == []


def test_refresh_respects_product_then_category_threshold_override(db_session, business_id):
    category = ProductCategory(business_id=business_id, name="Consumables", low_stock_threshold_days=Decimal("60"))
    db_session.add(category)
    db_session.flush()

    # stock=5, 5 units sold in the 30-day window -> ~30.0 days cover.
    # Category default (60 days) would flag this product; a product-level
    # override of 1 day should suppress the alert instead.
    product = _make_product(
        db_session, business_id, name="Override Product", category_id=category.id, low_stock_threshold_days=Decimal("1")
    )
    _make_sale(db_session, business_id, product_id=product.id, quantity=5, sold_at=datetime.now(timezone.utc))
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=10, reason="purchase")
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=-5, reason="sale")
    db_session.commit()

    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product.id})
    assert AlertRepository(db_session).list_active_for_business(business_id) == []

    # Same stock/sales picture (~30.0 days cover), but no product-level
    # override this time — the category's 60-day threshold should now
    # catch it (30.0 <= 60), unlike the global 7-day default.
    product_2 = _make_product(db_session, business_id, name="Category Only", category_id=category.id)
    _make_sale(db_session, business_id, product_id=product_2.id, quantity=5, sold_at=datetime.now(timezone.utc))
    _make_movement(db_session, business_id, product_id=product_2.id, quantity_delta=10, reason="purchase")
    _make_movement(db_session, business_id, product_id=product_2.id, quantity_delta=-5, reason="sale")
    db_session.commit()

    refresh_low_stock_alerts(db_session, business_id=business_id, product_ids={product_2.id})
    alerts = AlertRepository(db_session).list_active_for_business(business_id)
    assert len(alerts) == 1
    assert alerts[0].product_id == product_2.id
