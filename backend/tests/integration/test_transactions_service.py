"""Application-layer tests for the dashboard's raw transaction drill-down
(Gap 5) — pagination, filters, and PII minimization. See
tests/tenant_isolation/test_transactions_isolation.py for the HTTP-level
cross-tenant boundary and pagination-cap enforcement.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.transactions import (
    MAX_PAGE_SIZE,
    list_purchase_transactions,
    list_repair_transactions,
    list_sale_transactions,
)
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product, ProductCategory
from app.models.production_event import ProductionEvent
from app.models.sale import Sale, SaleItem
from app.repositories.supplier import SupplierRepository


def _make_product(db_session, business_id, name="Chain Lube", category_id=None):
    product = Product(business_id=business_id, name=name, sku=None, cost_price=None, sell_price=None, category_id=category_id)
    db_session.add(product)
    db_session.commit()
    return product


def _make_sale(db_session, business_id, product_id, *, sold_at, quantity=1, unit_price=Decimal("10.00")):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=unit_price * quantity)
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(business_id=business_id, sale_id=sale.id, product_id=product_id, quantity=quantity, unit_price=unit_price)
    )
    db_session.commit()
    return sale


def test_list_sale_transactions_returns_line_items_with_no_pii(db_session, business_id):
    product = _make_product(db_session, business_id)
    _make_sale(db_session, business_id, product.id, sold_at=datetime(2026, 1, 5, tzinfo=timezone.utc))

    result = list_sale_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=None, category_id=None
    )
    assert result.total == 1
    row = result.items[0]
    assert row.product_name == "Chain Lube"
    # No customer name/email/phone anywhere on this row at all — the
    # dataclass itself has no such field, so there's nothing to
    # accidentally leak here regardless of what's in the DB.
    assert not hasattr(row, "customer_name")
    assert not hasattr(row, "customer_email")


def test_list_sale_transactions_filters_by_product_and_category(db_session, business_id):
    category = ProductCategory(business_id=business_id, name="Lubricants")
    db_session.add(category)
    db_session.commit()
    matching = _make_product(db_session, business_id, name="In Category", category_id=category.id)
    other = _make_product(db_session, business_id, name="Not In Category")
    _make_sale(db_session, business_id, matching.id, sold_at=datetime(2026, 1, 5, tzinfo=timezone.utc))
    _make_sale(db_session, business_id, other.id, sold_at=datetime(2026, 1, 5, tzinfo=timezone.utc))

    by_category = list_sale_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=None, category_id=category.id
    )
    assert by_category.total == 1
    assert by_category.items[0].product_name == "In Category"

    by_product = list_sale_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=other.id, category_id=None
    )
    assert by_product.total == 1
    assert by_product.items[0].product_name == "Not In Category"


def test_list_sale_transactions_filters_by_date_range(db_session, business_id):
    product = _make_product(db_session, business_id)
    _make_sale(db_session, business_id, product.id, sold_at=datetime(2026, 1, 5, tzinfo=timezone.utc))
    _make_sale(db_session, business_id, product.id, sold_at=datetime(2026, 6, 5, tzinfo=timezone.utc))

    result = list_sale_transactions(
        db_session, business_id=business_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        product_id=None, category_id=None,
    )
    assert result.total == 1


def test_list_sale_transactions_pagination_is_stable_and_capped(db_session, business_id):
    product = _make_product(db_session, business_id)
    for i in range(5):
        _make_sale(db_session, business_id, product.id, sold_at=datetime(2026, 1, 1 + i, tzinfo=timezone.utc))

    page1 = list_sale_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=None, category_id=None,
        limit=2, offset=0,
    )
    page2 = list_sale_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=None, category_id=None,
        limit=2, offset=2,
    )
    assert page1.total == 5
    assert len(page1.items) == 2
    assert len(page2.items) == 2
    # No overlap between pages — stable ordering.
    assert {r.id for r in page1.items}.isdisjoint({r.id for r in page2.items})

    # A caller asking for more than MAX_PAGE_SIZE never gets more than
    # the cap — this is the actual enforcement point, not just the API
    # route's Query(le=...) (which a direct call to this function, or a
    # future second caller, could otherwise bypass).
    uncapped = list_sale_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=None, category_id=None,
        limit=MAX_PAGE_SIZE + 500, offset=0,
    )
    assert uncapped.limit == MAX_PAGE_SIZE


def test_list_purchase_transactions_includes_supplier_name(db_session, business_id):
    product = _make_product(db_session, business_id)
    supplier = SupplierRepository(db_session).create(business_id=business_id, name="Acme Parts", contact_info=None)
    db_session.add(
        InventoryMovement(
            business_id=business_id, product_id=product.id, quantity_delta=10, reason="purchase",
            event_date=date(2026, 1, 5), unit_cost=Decimal("2.50"), supplier_id=supplier.id,
        )
    )
    db_session.commit()

    result = list_purchase_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=None, category_id=None
    )
    assert result.total == 1
    assert result.items[0].supplier_name == "Acme Parts"


def test_list_purchase_transactions_unknown_supplier_is_none_not_an_error(db_session, business_id):
    product = _make_product(db_session, business_id)
    db_session.add(
        InventoryMovement(
            business_id=business_id, product_id=product.id, quantity_delta=10, reason="purchase",
            event_date=date(2026, 1, 5), unit_cost=Decimal("2.50"), supplier_id=None,
        )
    )
    db_session.commit()

    result = list_purchase_transactions(
        db_session, business_id=business_id, start_date=None, end_date=None, product_id=None, category_id=None
    )
    assert result.items[0].supplier_id is None
    assert result.items[0].supplier_name is None


def test_list_repair_transactions_has_no_customer_identity(db_session, business_id):
    db_session.add(
        ProductionEvent(
            business_id=business_id, event_type="repair", description="Brake service", status="completed",
            opened_at=datetime(2026, 1, 5, tzinfo=timezone.utc), completed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            price_charged=Decimal("45.00"), labour_cost=Decimal("20.00"),
        )
    )
    db_session.commit()

    result = list_repair_transactions(db_session, business_id=business_id, start_date=None, end_date=None)
    assert result.total == 1
    row = result.items[0]
    assert not hasattr(row, "customer_name")
    assert row.description == "Brake service"
