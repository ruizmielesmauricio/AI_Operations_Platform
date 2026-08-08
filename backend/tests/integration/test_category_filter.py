"""Covers the category_id filter on get_financial_performance/
get_retail_operations/get_forecast/get_findings, and get_category_breakdown
end to end, against a real (SQLite) database — mirrors
test_analytics_repositories.py's seeding conventions, extended with two
products in different categories plus one uncategorized product.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.category_breakdown import get_category_breakdown
from app.application.financial_performance import get_financial_performance
from app.application.findings import get_findings
from app.application.forecast import get_forecast
from app.application.retail_operations import get_retail_operations
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product, ProductCategory
from app.models.sale import Sale, SaleItem

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 7)


def _make_category(db_session, business_id, name):
    category = ProductCategory(business_id=business_id, name=name)
    db_session.add(category)
    db_session.flush()
    return category


def _make_product(db_session, business_id, *, name, category_id=None, cost_price=None, sell_price=None):
    product = Product(
        business_id=business_id, sku=None, name=name, category_id=category_id,
        cost_price=cost_price, sell_price=sell_price,
    )
    db_session.add(product)
    db_session.flush()
    return product


def _make_sale(db_session, business_id, *, sold_at, product_id, quantity, unit_price, cost_price_at_sale=None):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=unit_price * quantity, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(
        business_id=business_id, sale_id=sale.id, product_id=product_id, quantity=quantity,
        unit_price=unit_price, cost_price_at_sale=cost_price_at_sale,
    )
    db_session.add(item)
    db_session.flush()


def _make_movement(db_session, business_id, *, product_id, quantity_delta, reason, unit_cost=None, event_date=None):
    movement = InventoryMovement(
        business_id=business_id, product_id=product_id, quantity_delta=quantity_delta, reason=reason,
        unit_cost=unit_cost, event_date=event_date,
    )
    db_session.add(movement)
    db_session.flush()


def _seed(db_session, business_id):
    parts = _make_category(db_session, business_id, "Parts")
    accessories = _make_category(db_session, business_id, "Accessories")

    chain_lube = _make_product(
        db_session, business_id, name="Chain Lube", category_id=parts.id,
        cost_price=Decimal("5.00"), sell_price=Decimal("10.00"),
    )
    bar_tape = _make_product(
        db_session, business_id, name="Bar Tape", category_id=accessories.id,
        cost_price=Decimal("3.00"), sell_price=Decimal("20.00"),
    )
    uncategorized = _make_product(
        db_session, business_id, name="Mystery Item", category_id=None,
        cost_price=Decimal("1.00"), sell_price=Decimal("2.00"),
    )

    _make_sale(
        db_session, business_id, sold_at=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
        product_id=chain_lube.id, quantity=10, unit_price=Decimal("10.00"), cost_price_at_sale=Decimal("5.00"),
    )
    _make_sale(
        db_session, business_id, sold_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        product_id=bar_tape.id, quantity=2, unit_price=Decimal("20.00"), cost_price_at_sale=Decimal("3.00"),
    )
    _make_sale(
        db_session, business_id, sold_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        product_id=uncategorized.id, quantity=1, unit_price=Decimal("2.00"), cost_price_at_sale=Decimal("1.00"),
    )

    _make_movement(db_session, business_id, product_id=chain_lube.id, quantity_delta=50, reason="purchase")
    _make_movement(db_session, business_id, product_id=chain_lube.id, quantity_delta=-10, reason="sale")
    _make_movement(db_session, business_id, product_id=bar_tape.id, quantity_delta=20, reason="purchase")
    _make_movement(db_session, business_id, product_id=bar_tape.id, quantity_delta=-2, reason="sale")
    _make_movement(
        db_session, business_id, product_id=chain_lube.id, quantity_delta=15, reason="purchase",
        unit_cost=Decimal("4.00"), event_date=date(2026, 1, 4),
    )

    db_session.commit()
    return parts, accessories, chain_lube, bar_tape, uncategorized


def test_financial_performance_with_category_id_only_includes_that_category(db_session, business_id):
    parts, _accessories, chain_lube, _bar_tape, _uncategorized = _seed(db_session, business_id)

    summary = get_financial_performance(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END, category_id=parts.id
    )

    assert summary.revenue.current == Decimal("100.00")  # only Chain Lube's revenue
    assert [row.product_id for row in summary.top_margin_products] == [chain_lube.id]


def test_financial_performance_without_category_id_includes_everything(db_session, business_id):
    _seed(db_session, business_id)

    summary = get_financial_performance(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END
    )

    assert summary.revenue.current == Decimal("142.00")  # 100 + 40 + 2, all three products


def test_financial_performance_with_an_unknown_category_id_returns_zero_revenue_not_an_error(db_session, business_id):
    _seed(db_session, business_id)

    summary = get_financial_performance(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END,
        category_id=uuid.uuid4(),
    )

    assert summary.revenue.current == Decimal("0")
    assert summary.top_margin_products == []


def test_retail_operations_with_category_id_scopes_stock_and_top_sellers(db_session, business_id):
    _parts, accessories, _chain_lube, bar_tape, _uncategorized = _seed(db_session, business_id)

    summary = get_retail_operations(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END,
        category_id=accessories.id,
    )

    assert [row.product_id for row in summary.top_sellers_by_units] == [bar_tape.id]
    assert {row.product_id for row in summary.stock_cover} == {bar_tape.id}
    assert summary.inventory_value.value_at_cost == Decimal("54.00")  # 18 units * 3.00


def test_category_name_appears_on_every_product_row_regardless_of_filter(db_session, business_id):
    parts, _accessories, chain_lube, _bar_tape, _uncategorized = _seed(db_session, business_id)

    summary = get_financial_performance(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END
    )
    row = next(r for r in summary.top_margin_products if r.product_id == chain_lube.id)
    assert row.category_name == "Parts"


def test_category_breakdown_end_to_end_including_uncategorized_bucket(db_session, business_id):
    parts, accessories, chain_lube, bar_tape, uncategorized = _seed(db_session, business_id)

    summary = get_category_breakdown(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END
    )

    rows_by_category = {row.category_id: row for row in summary.rows}
    assert rows_by_category[parts.id].revenue == Decimal("100.00")
    assert rows_by_category[parts.id].expenses == Decimal("60.00")  # 15 * 4.00, the only known-cost purchase
    assert rows_by_category[accessories.id].revenue == Decimal("40.00")
    assert rows_by_category[None].category_name == "Uncategorized"
    assert rows_by_category[None].revenue == Decimal("2.00")

    # Stock value at SELL price, not cost — deliberately different from
    # Retail Operations' own inventory_value (which stays at cost).
    assert rows_by_category[parts.id].stock_value == Decimal("550.00")  # 55 units * 10.00 sell price


# --- get_forecast's category_id filter -------------------------------------


def test_forecast_category_id_only_considers_products_in_that_category(db_session, business_id):
    parts, accessories, _chain_lube, _bar_tape, _uncategorized = _seed(db_session, business_id)
    now = datetime(2026, 1, 8, tzinfo=timezone.utc)

    # None of the seeded products have anywhere near 14 days of sales
    # history, so every one of them lands in products_excluded_insufficient_data
    # rather than the real products list — a simple, direct way to prove
    # which products were even considered, without needing enough history
    # to produce a real forecast.
    unfiltered = get_forecast(db_session, business_id=business_id, now=now)
    assert unfiltered.products_excluded_insufficient_data == 3  # all three seeded products

    filtered_to_parts = get_forecast(db_session, business_id=business_id, now=now, category_id=parts.id)
    assert filtered_to_parts.products_excluded_insufficient_data == 1  # only Chain Lube

    filtered_to_accessories = get_forecast(db_session, business_id=business_id, now=now, category_id=accessories.id)
    assert filtered_to_accessories.products_excluded_insufficient_data == 1  # only Bar Tape


def test_forecast_with_an_unknown_category_id_considers_zero_products(db_session, business_id):
    _seed(db_session, business_id)
    now = datetime(2026, 1, 8, tzinfo=timezone.utc)

    summary = get_forecast(db_session, business_id=business_id, now=now, category_id=uuid.uuid4())
    assert summary.products == []
    assert summary.products_excluded_insufficient_data == 0


# --- get_findings's category_id filter --------------------------------------


def _seed_findings_scenario(db_session, business_id):
    """A category (Parts) with a known-cost sale, and a second category
    (Accessories) with stock but zero sales at all (a dead_stock trigger)
    plus enough unknown-cost revenue to also trip the whole-business
    incomplete_cost_data rule (< 50% of revenue has a known cost)."""
    parts = _make_category(db_session, business_id, "Parts")
    accessories = _make_category(db_session, business_id, "Accessories")

    known_cost_product = _make_product(
        db_session, business_id, name="Known Cost Widget", category_id=parts.id, cost_price=Decimal("5.00")
    )
    dead_stock_product = _make_product(
        db_session, business_id, name="Dead Stock Widget", category_id=accessories.id, cost_price=Decimal("2.00")
    )

    # Known-cost sale: revenue 10.00, all cost-known.
    _make_sale(
        db_session, business_id, sold_at=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
        product_id=known_cost_product.id, quantity=1, unit_price=Decimal("10.00"), cost_price_at_sale=Decimal("5.00"),
    )
    # Unknown-cost sale on a third, uncategorized product — pushes total
    # revenue's known-cost share below the 50% incomplete_cost_data
    # threshold, without affecting either named category's own numbers.
    unknown_cost_product = _make_product(db_session, business_id, name="Unknown Cost Widget", cost_price=None)
    _make_sale(
        db_session, business_id, sold_at=datetime(2026, 1, 4, 12, 0, tzinfo=timezone.utc),
        product_id=unknown_cost_product.id, quantity=1, unit_price=Decimal("50.00"), cost_price_at_sale=None,
    )

    # Dead stock: has stock on hand, zero sales in the period at all.
    _make_movement(db_session, business_id, product_id=dead_stock_product.id, quantity_delta=20, reason="purchase")

    db_session.commit()
    return parts, accessories, known_cost_product, dead_stock_product


def test_findings_category_id_scopes_per_product_rules_only(db_session, business_id):
    parts, accessories, _known, dead_stock_product = _seed_findings_scenario(db_session, business_id)

    unfiltered = get_findings(db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END)
    unfiltered_types = {f.type for f in unfiltered.findings}
    assert "dead_stock" in unfiltered_types

    # Filtered to the dead-stock product's own category — the finding
    # still shows up.
    filtered_to_accessories = get_findings(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END, category_id=accessories.id
    )
    dead_stock_findings = [f for f in filtered_to_accessories.findings if f.type == "dead_stock"]
    assert len(dead_stock_findings) == 1
    assert dead_stock_findings[0].evidence["product_id"] == str(dead_stock_product.id)

    # Filtered to a different category — the dead-stock product isn't in
    # it, so its finding is correctly excluded.
    filtered_to_parts = get_findings(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END, category_id=parts.id
    )
    assert "dead_stock" not in {f.type for f in filtered_to_parts.findings}


def test_findings_category_id_never_scopes_whole_business_rules(db_session, business_id):
    parts, _accessories, _known, _dead_stock_product = _seed_findings_scenario(db_session, business_id)

    unfiltered = get_findings(db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END)
    unfiltered_incomplete = next(f for f in unfiltered.findings if f.type == "incomplete_cost_data")

    # Filtered to "Parts" (whose own revenue is only 10.00, entirely
    # cost-known) — if incomplete_cost_data were wrongly recomputed
    # against the filtered category alone, it wouldn't trigger at all
    # (100% coverage). It must still reflect the exact same whole-business
    # figures as the unfiltered call, per direct instruction that a
    # revenue/margin-level finding is a business-wide trend, not
    # something a stock filter should change the meaning of.
    filtered = get_findings(
        db_session, business_id=business_id, start_date=_PERIOD_START, end_date=_PERIOD_END, category_id=parts.id
    )
    filtered_incomplete = next(f for f in filtered.findings if f.type == "incomplete_cost_data")

    assert filtered_incomplete.evidence["total_revenue"] == unfiltered_incomplete.evidence["total_revenue"]
    assert filtered_incomplete.evidence["revenue_with_known_cost"] == unfiltered_incomplete.evidence["revenue_with_known_cost"]
