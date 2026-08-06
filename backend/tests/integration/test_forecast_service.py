"""Stage C13 — verifies app/application/forecast.py's SQL wiring
(repository queries, business-local day bucketing, stock lookup) against a
real (SQLite) database. The pure math itself is already covered by
tests/unit/test_forecasting.py's hand-computed fixtures — this file only
needs to prove the orchestration reads the right rows and produces sane
end-to-end numbers.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.application.forecast import get_forecast
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem

# February in Dublin (the default business timezone) is GMT — UTC+0, no
# DST offset to account for — keeping the fixture data's UTC timestamps
# equal to local wall-clock time.
_TODAY = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)


def _make_product(db_session, business_id, *, name):
    product = Product(business_id=business_id, sku=None, name=name, cost_price=Decimal("5.00"), sell_price=Decimal("10.00"))
    db_session.add(product)
    db_session.flush()
    return product


def _make_daily_sale(db_session, business_id, *, sold_at, product_id, quantity, unit_price=Decimal("10.00")):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=unit_price * quantity, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(
        business_id=business_id,
        sale_id=sale.id,
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price,
        cost_price_at_sale=Decimal("5.00"),
    )
    db_session.add(item)
    db_session.flush()


def _make_movement(db_session, business_id, *, product_id, quantity_delta, reason):
    movement = InventoryMovement(business_id=business_id, product_id=product_id, quantity_delta=quantity_delta, reason=reason)
    db_session.add(movement)
    db_session.flush()


def test_forecast_with_enough_history_produces_revenue_and_product_forecasts(db_session, business_id):
    selling_product = _make_product(db_session, business_id, name="Chain Lube")
    dead_product = _make_product(db_session, business_id, name="Never Sold")

    # 21 days of clean, constant demand (2 units/day) ending the day
    # before _TODAY — exactly at the seasonal threshold, and zero variance
    # by construction so the forecast numbers are exact, not approximate.
    for offset in range(1, 22):
        _make_daily_sale(
            db_session, business_id,
            sold_at=_TODAY - timedelta(days=offset),
            product_id=selling_product.id,
            quantity=2,
        )

    _make_movement(db_session, business_id, product_id=selling_product.id, quantity_delta=50, reason="purchase")
    _make_movement(db_session, business_id, product_id=selling_product.id, quantity_delta=-42, reason="sale")  # 21 * 2
    db_session.commit()

    summary = get_forecast(db_session, business_id=business_id, horizon_days=7, now=_TODAY)

    # Revenue: 21 days at exactly 20.00/day (2 units * 10.00), zero variance.
    assert summary.revenue.result.insufficient_data is False
    assert summary.revenue.result.method == "seasonal_day_of_week"
    assert summary.revenue.result.total_point == Decimal("140.00")  # 20.00 * 7
    assert summary.revenue.result.total_low == summary.revenue.result.total_point
    assert summary.revenue.result.total_high == summary.revenue.result.total_point

    # Only the selling product gets a forecast — the never-sold product is
    # excluded, not forecast as literally zero demand.
    assert len(summary.products) == 1
    assert summary.products_excluded_insufficient_data == 1

    product_forecast = summary.products[0]
    assert product_forecast.product_id == selling_product.id
    assert product_forecast.result.total_point == Decimal("14.0")  # 2 units/day * 7 days
    assert product_forecast.current_stock == 8  # 50 - 42
    # ceil(total_high) - current_stock = ceil(14.0) - 8 = 6
    assert product_forecast.suggested_reorder_quantity == 6
    assert product_forecast.days_of_cover_at_forecast_rate == Decimal("4.0")  # 8 stock / 2 per day

    assert dead_product.id not in {p.product_id for p in summary.products}


def test_forecast_with_negative_derived_stock_reports_zero_cover_not_a_negative_number(db_session, business_id):
    # Derived stock can go negative (e.g. sales recorded with no matching
    # purchase/inventory-count import yet, a real data-completeness issue
    # elsewhere in the platform) — days_of_cover_at_forecast_rate must
    # clamp to 0, the same convention app/analytics/retail.py's
    # compute_stock_cover_days already uses, not divide through into a
    # nonsensical negative day count.
    product = _make_product(db_session, business_id, name="Overdrawn")
    for offset in range(1, 22):
        _make_daily_sale(db_session, business_id, sold_at=_TODAY - timedelta(days=offset), product_id=product.id, quantity=2)
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=-10, reason="sale")  # no purchase at all
    db_session.commit()

    summary = get_forecast(db_session, business_id=business_id, horizon_days=7, now=_TODAY)

    assert len(summary.products) == 1
    product_forecast = summary.products[0]
    assert product_forecast.current_stock == -10
    assert product_forecast.days_of_cover_at_forecast_rate == Decimal("0")
    # A negative starting stock only increases how much is needed to
    # actually cover both the deficit and forecast demand.
    assert product_forecast.suggested_reorder_quantity == 14 + 10  # ceil(14.0 total_high) - (-10)


def test_forecast_below_minimum_history_reports_insufficient_data_for_everything(db_session, business_id):
    product = _make_product(db_session, business_id, name="Too New")
    # Only 5 days of history — under forecasting.py's MIN_HISTORY_DAYS (14).
    for offset in range(1, 6):
        _make_daily_sale(db_session, business_id, sold_at=_TODAY - timedelta(days=offset), product_id=product.id, quantity=1)
    db_session.commit()

    summary = get_forecast(db_session, business_id=business_id, horizon_days=7, now=_TODAY)

    assert summary.revenue.result.insufficient_data is True
    assert summary.revenue.result.total_point == Decimal("0")
    assert summary.products == []
    assert summary.products_excluded_insufficient_data == 1


def test_forecast_for_a_business_with_no_sales_at_all_is_insufficient_data(db_session, business_id):
    summary = get_forecast(db_session, business_id=business_id, horizon_days=7, now=_TODAY)

    assert summary.revenue.result.insufficient_data is True
    assert summary.products == []
    assert summary.products_excluded_insufficient_data == 0  # no catalog products to exclude either
