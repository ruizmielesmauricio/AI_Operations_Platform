"""Application-layer tests for the global search bar (Notification Centre +
search batch) — one free-text query, grouped by result type, tenant-scoped
to a single business. See tests/tenant_isolation/test_search_isolation.py
for the HTTP-level cross-tenant/branch boundary and non-member 403 cases.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.search import MIN_QUERY_LENGTH, global_search
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.production_event import ProductionEvent
from app.models.sale import Sale, SaleItem
from app.repositories.supplier import SupplierRepository


def _make_product(db_session, business_id, name="Chain Lube", sku=None):
    product = Product(business_id=business_id, name=name, sku=sku, cost_price=None, sell_price=None)
    db_session.add(product)
    db_session.commit()
    return product


def _make_sale(db_session, business_id, product_id, *, order_reference=None, sold_at=None):
    sale = Sale(
        business_id=business_id,
        sold_at=sold_at or datetime(2026, 1, 5, tzinfo=timezone.utc),
        total_amount=Decimal("10.00"),
        order_reference=order_reference,
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(business_id=business_id, sale_id=sale.id, product_id=product_id, quantity=1, unit_price=Decimal("10.00"))
    )
    db_session.commit()
    return sale


def test_search_matches_product_by_name(db_session, business_id):
    _make_product(db_session, business_id, name="Continental GP5000 Tyre")
    _make_product(db_session, business_id, name="Brake Pads")

    result = global_search(db_session, business_id=business_id, query="continental")
    assert [p.name for p in result.products] == ["Continental GP5000 Tyre"]


def test_search_matches_product_by_sku(db_session, business_id):
    _make_product(db_session, business_id, name="Chain Lube", sku="LUBE-500")

    result = global_search(db_session, business_id=business_id, query="LUBE-500")
    assert len(result.products) == 1
    assert result.products[0].sku == "LUBE-500"


def test_search_matches_sale_by_order_reference(db_session, business_id):
    product = _make_product(db_session, business_id, name="Chain Lube")
    _make_sale(db_session, business_id, product.id, order_reference="ORD-9182")
    _make_sale(db_session, business_id, product.id, order_reference="ORD-0001")

    result = global_search(db_session, business_id=business_id, query="ORD-9182")
    assert len(result.sales) == 1
    assert result.sales[0].order_reference == "ORD-9182"
    assert result.sales[0].product_name == "Chain Lube"


def test_search_matches_purchase_by_purchase_reference(db_session, business_id):
    product = _make_product(db_session, business_id, name="Chain Lube")
    db_session.add(
        InventoryMovement(
            business_id=business_id, product_id=product.id, quantity_delta=10, reason="purchase",
            event_date=date(2026, 1, 5), unit_cost=Decimal("2.50"), purchase_reference="PO-4471",
        )
    )
    db_session.add(
        InventoryMovement(
            business_id=business_id, product_id=product.id, quantity_delta=10, reason="purchase",
            event_date=date(2026, 1, 6), unit_cost=Decimal("2.50"), purchase_reference="PO-0009",
        )
    )
    db_session.commit()

    result = global_search(db_session, business_id=business_id, query="PO-4471")
    assert len(result.purchases) == 1
    assert result.purchases[0].purchase_reference == "PO-4471"


def test_search_matches_supplier_by_name(db_session, business_id):
    SupplierRepository(db_session).create(business_id=business_id, name="Acme Parts Ltd", contact_info=None)
    SupplierRepository(db_session).create(business_id=business_id, name="Other Co", contact_info=None)

    result = global_search(db_session, business_id=business_id, query="acme")
    assert [s.name for s in result.suppliers] == ["Acme Parts Ltd"]


def test_search_matches_repair_by_reference_and_description(db_session, business_id):
    db_session.add(
        ProductionEvent(
            business_id=business_id, event_type="repair", description="Full brake service",
            status="completed", opened_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 5, tzinfo=timezone.utc), price_charged=Decimal("45.00"),
            labour_cost=Decimal("20.00"), repair_reference="JOB-364",
        )
    )
    db_session.commit()

    by_reference = global_search(db_session, business_id=business_id, query="JOB-364")
    assert len(by_reference.repairs) == 1

    by_description = global_search(db_session, business_id=business_id, query="brake service")
    assert len(by_description.repairs) == 1


def test_search_results_contain_no_customer_pii(db_session, business_id):
    product = _make_product(db_session, business_id, name="Chain Lube")
    _make_sale(db_session, business_id, product.id, order_reference="ORD-1")
    db_session.add(
        ProductionEvent(
            business_id=business_id, event_type="repair", description="Brake service", status="completed",
            opened_at=datetime(2026, 1, 5, tzinfo=timezone.utc), completed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            price_charged=Decimal("45.00"), labour_cost=Decimal("20.00"), repair_reference="ORD-1",
        )
    )
    db_session.commit()

    result = global_search(db_session, business_id=business_id, query="ORD-1")
    for row in [*result.sales, *result.repairs]:
        assert not hasattr(row, "customer_name")
        assert not hasattr(row, "customer_email")
        assert not hasattr(row, "customer_id")


def test_search_result_limits_are_enforced_per_group(db_session, business_id):
    for i in range(8):
        _make_product(db_session, business_id, name=f"Widget {i}")

    result = global_search(db_session, business_id=business_id, query="widget", limit=3)
    assert len(result.products) == 3


def test_search_below_minimum_query_length_returns_empty_not_an_error(db_session, business_id):
    _make_product(db_session, business_id, name="Chain Lube")

    short_query = "c" * (MIN_QUERY_LENGTH - 1)
    result = global_search(db_session, business_id=business_id, query=short_query)
    assert result.products == []
    assert result.sales == []
    assert result.purchases == []
    assert result.suppliers == []
    assert result.repairs == []


def test_search_repairs_group_is_absent_for_non_bicycle_shop_template(db_session):
    from app.models.business import Business

    business = Business(name="Coffee Corner", template="coffee_shop")
    db_session.add(business)
    db_session.commit()
    db_session.add(
        ProductionEvent(
            business_id=business.id, event_type="repair", description="Espresso machine descale",
            status="completed", opened_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 5, tzinfo=timezone.utc), repair_reference="JOB-1",
        )
    )
    db_session.commit()

    result = global_search(db_session, business_id=business.id, query="descale")
    assert result.repairs == []
