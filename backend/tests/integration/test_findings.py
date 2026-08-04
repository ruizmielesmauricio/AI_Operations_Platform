"""Stage C10 — verifies app/application/findings.py wires the existing C9
application functions (get_financial_performance, get_retail_operations)
into the pure rules in app/analytics/findings.py correctly, against a real
(SQLite) database. Deliberately seeds a scenario that trips every rule at
once, including the case that caught a real bug during design: a
loss-making product with few peers, which rank_products_by_margin puts in
top_margin_products (not bottom_margin_products) because there aren't
enough products to populate a distinct bottom list.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.findings import get_findings
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem

_PREVIOUS_PERIOD_START = date(2025, 12, 25)
_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 7)  # inclusive


def _make_product(db_session, business_id, *, name, cost_price):
    product = Product(business_id=business_id, sku=None, name=name, cost_price=cost_price, sell_price=cost_price)
    db_session.add(product)
    db_session.flush()
    return product


def _make_sale_with_item(db_session, business_id, *, sold_at, product_id, quantity, unit_price, cost_price_at_sale):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=unit_price * quantity, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            business_id=business_id,
            sale_id=sale.id,
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
            cost_price_at_sale=cost_price_at_sale,
        )
    )
    db_session.flush()


def _make_movement(db_session, business_id, *, product_id, quantity_delta, reason):
    db_session.add(
        InventoryMovement(business_id=business_id, product_id=product_id, quantity_delta=quantity_delta, reason=reason)
    )
    db_session.flush()


def test_get_findings_end_to_end(db_session, business_id):
    loss_leader = _make_product(db_session, business_id, name="Loss Leader", cost_price=Decimal("10.00"))
    slow_stock = _make_product(db_session, business_id, name="Slow Stock", cost_price=Decimal("5.00"))
    almost_out = _make_product(db_session, business_id, name="Almost Out", cost_price=Decimal("3.00"))
    no_cost_data = _make_product(db_session, business_id, name="No Cost Data", cost_price=None)

    # Previous period (Dec 25-31 2025): one big sale, so the current
    # period's lower total trips revenue_decline.
    _make_sale_with_item(
        db_session,
        business_id,
        sold_at=datetime(2025, 12, 28, 12, 0, tzinfo=timezone.utc),
        product_id=loss_leader.id,
        quantity=5,
        unit_price=Decimal("200.00"),
        cost_price_at_sale=Decimal("10.00"),
    )

    # Current period (Jan 1-7 2026):
    # Loss Leader: sells below cost -> product_selling_at_loss. Only 2
    # products end up with known-cost revenue this period (this one and
    # Almost Out), so rank_products_by_margin's default top_n=5 means both
    # land in top_margin_products and bottom_margin_products stays empty —
    # this is the case that must still be caught.
    _make_sale_with_item(
        db_session,
        business_id,
        sold_at=datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc),
        product_id=loss_leader.id,
        quantity=5,
        unit_price=Decimal("8.00"),
        cost_price_at_sale=Decimal("10.00"),
    )
    _make_movement(db_session, business_id, product_id=loss_leader.id, quantity_delta=20, reason="purchase")
    _make_movement(db_session, business_id, product_id=loss_leader.id, quantity_delta=-5, reason="sale")

    # Slow Stock: stock on hand, zero sales this period -> dead_stock.
    _make_movement(db_session, business_id, product_id=slow_stock.id, quantity_delta=20, reason="purchase")

    # Almost Out: sells fast relative to a small remaining stock -> low_stock.
    _make_sale_with_item(
        db_session,
        business_id,
        sold_at=datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc),
        product_id=almost_out.id,
        quantity=35,
        unit_price=Decimal("4.00"),
        cost_price_at_sale=Decimal("3.00"),
    )
    _make_movement(db_session, business_id, product_id=almost_out.id, quantity_delta=40, reason="purchase")
    _make_movement(db_session, business_id, product_id=almost_out.id, quantity_delta=-35, reason="sale")

    # No Cost Data: big revenue, no cost_price_at_sale -> drags down
    # cost_data_coverage_pct; plenty of stock so it doesn't also trip
    # low_stock and confound that assertion.
    _make_sale_with_item(
        db_session,
        business_id,
        sold_at=datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc),
        product_id=no_cost_data.id,
        quantity=10,
        unit_price=Decimal("50.00"),
        cost_price_at_sale=None,
    )
    _make_movement(db_session, business_id, product_id=no_cost_data.id, quantity_delta=60, reason="purchase")
    _make_movement(db_session, business_id, product_id=no_cost_data.id, quantity_delta=-10, reason="sale")

    db_session.commit()

    summary = get_findings(db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END)

    finding_types = {f.type for f in summary.findings}
    assert finding_types == {
        "revenue_decline",
        "low_gross_margin",
        "incomplete_cost_data",
        "product_selling_at_loss",
        "low_stock",
        "dead_stock",
    }

    # The bug this test was written to catch: Loss Leader must be flagged
    # even though it ends up in top_margin_products, not bottom.
    loss_findings = [f for f in summary.findings if f.type == "product_selling_at_loss"]
    assert len(loss_findings) == 1
    assert loss_findings[0].evidence["product_id"] == str(loss_leader.id)

    low_stock_findings = [f for f in summary.findings if f.type == "low_stock"]
    assert len(low_stock_findings) == 1
    assert low_stock_findings[0].evidence["product_id"] == str(almost_out.id)

    dead_stock_findings = [f for f in summary.findings if f.type == "dead_stock"]
    assert len(dead_stock_findings) == 1
    assert dead_stock_findings[0].evidence["product_id"] == str(slow_stock.id)

    # Every recommendation traces back to a real finding type, and the
    # critical/warning findings outrank the info-level ones.
    assert len(summary.recommendations) == len(summary.findings)
    severities = [r.severity for r in summary.recommendations]
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s])
