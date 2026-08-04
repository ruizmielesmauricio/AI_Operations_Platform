"""Stage C9 — verifies the new aggregate repository queries and the
application-layer orchestration (app/application/financial_performance.py,
app/application/retail_operations.py) against a real (SQLite) database,
since the unit tests in tests/unit/ exercise the pure formulas with
hand-built inputs and can't catch a wrong SQL aggregate on their own.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.financial_performance import get_financial_performance
from app.application.retail_operations import get_retail_operations
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.sale import SaleRepository
from app.repositories.sale_item import SaleItemRepository

# January in Dublin (the default business timezone) is GMT — UTC+0 — with
# no DST offset to account for, keeping the fixture data's UTC timestamps
# equal to local wall-clock time.
_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 7)  # inclusive


def _make_product(db_session, business_id, *, name, cost_price, sell_price=None):
    product = Product(
        business_id=business_id,
        sku=None,
        name=name,
        cost_price=cost_price,
        sell_price=sell_price if sell_price is not None else cost_price,
    )
    db_session.add(product)
    db_session.flush()
    return product


def _make_sale_with_item(db_session, business_id, *, sold_at, product_id, quantity, unit_price, cost_price_at_sale):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=unit_price * quantity, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(
        business_id=business_id,
        sale_id=sale.id,
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price,
        cost_price_at_sale=cost_price_at_sale,
    )
    db_session.add(item)
    db_session.flush()
    return sale, item


def _make_movement(db_session, business_id, *, product_id, quantity_delta, reason):
    movement = InventoryMovement(business_id=business_id, product_id=product_id, quantity_delta=quantity_delta, reason=reason)
    db_session.add(movement)
    db_session.flush()


def _seed(db_session, business_id):
    product_1 = _make_product(db_session, business_id, name="Chain Lube", cost_price=Decimal("5.00"))
    product_2 = _make_product(db_session, business_id, name="Bar Tape", cost_price=None, sell_price=Decimal("20.00"))

    # In-period sales.
    _make_sale_with_item(
        db_session,
        business_id,
        sold_at=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
        product_id=product_1.id,
        quantity=10,
        unit_price=Decimal("10.00"),
        cost_price_at_sale=Decimal("5.00"),
    )
    _make_sale_with_item(
        db_session,
        business_id,
        sold_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        product_id=product_2.id,
        quantity=2,
        unit_price=Decimal("20.00"),
        cost_price_at_sale=None,  # cost data not captured for this product
    )
    # Out-of-period sale — must not be counted.
    _make_sale_with_item(
        db_session,
        business_id,
        sold_at=datetime(2025, 12, 20, 12, 0, tzinfo=timezone.utc),
        product_id=product_1.id,
        quantity=99,
        unit_price=Decimal("10.00"),
        cost_price_at_sale=Decimal("5.00"),
    )

    # Stock: purchased in, then sold down.
    _make_movement(db_session, business_id, product_id=product_1.id, quantity_delta=50, reason="purchase")
    _make_movement(db_session, business_id, product_id=product_1.id, quantity_delta=-10, reason="sale")
    _make_movement(db_session, business_id, product_id=product_2.id, quantity_delta=20, reason="purchase")
    _make_movement(db_session, business_id, product_id=product_2.id, quantity_delta=-2, reason="sale")

    db_session.commit()
    return product_1, product_2


def test_sum_total_amount_in_range_excludes_sales_outside_the_window(db_session, business_id):
    _seed(db_session, business_id)

    total = SaleRepository(db_session).sum_total_amount_in_range(
        business_id,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert total == Decimal("140.00")  # 100.00 + 40.00, the Dec 2025 sale excluded


def test_aggregate_by_product_in_range_separates_known_and_unknown_cost(db_session, business_id):
    product_1, product_2 = _seed(db_session, business_id)

    aggregates = {
        a.product_id: a
        for a in SaleItemRepository(db_session).aggregate_by_product_in_range(
            business_id,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 8, tzinfo=timezone.utc),
        )
    }

    p1 = aggregates[product_1.id]
    assert p1.units_sold == 10
    assert p1.revenue == Decimal("100.00")
    assert p1.revenue_with_known_cost == Decimal("100.00")
    assert p1.cogs == Decimal("50.00")

    p2 = aggregates[product_2.id]
    assert p2.units_sold == 2
    assert p2.revenue == Decimal("40.00")
    assert p2.revenue_with_known_cost == Decimal("0")  # cost_price_at_sale was None
    assert p2.cogs == Decimal("0")


def test_get_financial_performance_end_to_end(db_session, business_id):
    _seed(db_session, business_id)

    summary = get_financial_performance(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END
    )

    assert summary.revenue.current == Decimal("140.00")
    assert summary.gross_margin.gross_profit == Decimal("50.00")
    assert summary.gross_margin.gross_margin_pct == Decimal("50.0")
    # 100 of 140 total revenue had known cost -> 71.4%
    assert summary.gross_margin.cost_data_coverage_pct == Decimal("71.4")
    assert summary.products_excluded_from_ranking == 1  # Bar Tape has no cost data
    assert [row.name for row in summary.top_margin_products] == ["Chain Lube"]


def test_get_retail_operations_end_to_end(db_session, business_id):
    product_1, product_2 = _seed(db_session, business_id)

    summary = get_retail_operations(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END
    )

    stock_by_id = {row.product_id: row for row in summary.stock_cover}
    assert stock_by_id[product_1.id].stock_on_hand == 40  # 50 purchased - 10 sold
    assert stock_by_id[product_2.id].stock_on_hand == 18  # 20 purchased - 2 sold

    assert summary.dead_stock == []  # both products sold in the period
    assert summary.inventory_value.value_at_cost == Decimal("200.00")  # only Chain Lube has a known cost (40 * 5.00)
    assert summary.inventory_value.products_missing_cost == 1  # Bar Tape has stock but no cost_price
    assert [row.name for row in summary.top_sellers] == ["Chain Lube", "Bar Tape"]
