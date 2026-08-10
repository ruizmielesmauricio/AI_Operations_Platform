"""Covers app/application/business_group.py against a real (SQLite)
database: resolve_authorized_group's membership/timezone gates, and the
sum-raw-inputs-then-recompute correctness of the group aggregation
functions (the class of bug this design specifically exists to avoid —
averaging two businesses' already-computed percentages instead of
recomputing one true rate from their summed raw figures).
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.application.business_group import (
    MixedTimezoneGroup,
    NotGroupMember,
    get_financial_performance_for_group,
    get_retail_operations_for_group,
    get_workshop_performance_for_group,
    resolve_authorized_group,
)
from app.application.financial_performance import get_financial_performance
from app.application.retail_operations import get_retail_operations
from app.application.workshop_performance import get_workshop_performance
from app.models.business import Business
from app.models.inventory_movement import InventoryMovement
from app.models.membership import Membership
from app.models.product import Product
from app.models.production_event import ProductionEvent
from app.models.sale import Sale, SaleItem

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 7)


def _make_product(db_session, business_id, *, name, cost_price):
    product = Product(business_id=business_id, sku=None, name=name, cost_price=cost_price, sell_price=cost_price)
    db_session.add(product)
    db_session.flush()
    return product


def _make_sale(db_session, business_id, *, sold_at, product_id, quantity, unit_price, cost_price_at_sale):
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


def _make_repair(db_session, business_id, *, completed_at, price_charged, labour_cost):
    db_session.add(
        ProductionEvent(
            business_id=business_id,
            event_type="repair",
            status="completed",
            opened_at=completed_at,
            completed_at=completed_at,
            price_charged=price_charged,
            labour_cost=labour_cost,
        )
    )
    db_session.flush()


@pytest.fixture
def group(db_session):
    """A primary shop and one branch, both the default Europe/Dublin
    timezone (matching Business.timezone's own default — no need to
    override it), owned by the same user, with a manager also on the
    branch specifically (proves resolve_authorized_group checks
    membership per business, not just "owns the parent")."""
    parent = Business(name="Primary Shop")
    branch = Business(name="Branch")
    db_session.add_all([parent, branch])
    db_session.flush()
    branch.parent_business_id = parent.id
    db_session.add(Membership(business_id=parent.id, user_id="owner", role="owner"))
    db_session.add(Membership(business_id=branch.id, user_id="owner", role="owner"))
    db_session.add(Membership(business_id=branch.id, user_id="branch-manager", role="manager"))
    db_session.commit()
    return parent, branch


def _seed_sales(db_session, business_id, *, revenue_multiplier=1):
    product = _make_product(db_session, business_id, name="Chain Lube", cost_price=Decimal("5.00"))
    _make_sale(
        db_session,
        business_id,
        sold_at=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
        product_id=product.id,
        quantity=10 * revenue_multiplier,
        unit_price=Decimal("10.00"),
        cost_price_at_sale=Decimal("5.00"),
    )
    _make_movement(db_session, business_id, product_id=product.id, quantity_delta=50, reason="purchase")
    db_session.commit()
    return product


# --- resolve_authorized_group -----------------------------------------


def test_resolve_authorized_group_returns_parent_and_branch(db_session, group):
    parent, branch = group
    resolved = resolve_authorized_group(db_session, business_id=parent.id, user_id="owner")
    assert {b.id for b in resolved} == {parent.id, branch.id}

    # Symmetric — starting from the branch resolves the same group.
    resolved_from_branch = resolve_authorized_group(db_session, business_id=branch.id, user_id="owner")
    assert {b.id for b in resolved_from_branch} == {parent.id, branch.id}


def test_resolve_authorized_group_rejects_a_caller_missing_from_any_member(db_session, group):
    parent, branch = group
    # branch-manager is only a member of the branch, not the parent — the
    # real security property: combining must fail, not silently return
    # only the businesses the caller happens to have access to.
    with pytest.raises(NotGroupMember):
        resolve_authorized_group(db_session, business_id=parent.id, user_id="branch-manager")


def test_resolve_authorized_group_rejects_mismatched_timezones(db_session, group):
    parent, branch = group
    branch.timezone = "America/New_York"
    db_session.commit()
    with pytest.raises(MixedTimezoneGroup):
        resolve_authorized_group(db_session, business_id=parent.id, user_id="owner")


# --- get_financial_performance_for_group --------------------------------


def test_group_financial_performance_sums_raw_revenue_not_averages_percentages(db_session, group):
    parent, branch = group
    _seed_sales(db_session, parent.id, revenue_multiplier=1)  # 10 units * €10 = €100
    _seed_sales(db_session, branch.id, revenue_multiplier=3)  # 30 units * €10 = €300

    parent_only = get_financial_performance(db_session, business_id=parent.id, start_date=_PERIOD_START, end_date=_PERIOD_END)
    branch_only = get_financial_performance(db_session, business_id=branch.id, start_date=_PERIOD_START, end_date=_PERIOD_END)
    combined = get_financial_performance_for_group(
        db_session, businesses=[parent, branch], start_date=_PERIOD_START, end_date=_PERIOD_END
    )

    assert combined.revenue.current == parent_only.revenue.current + branch_only.revenue.current
    assert combined.revenue.current == Decimal("400.00")
    # Both businesses' own products show up in the combined ranking —
    # never merged into one "Chain Lube" row despite the identical name,
    # since they're different Product rows (different business_id).
    assert len(combined.top_margin_products) == 2
    # Gross margin here happens to be identical for both businesses (same
    # cost_price/unit_price), so this alone wouldn't catch an averaging
    # bug — the real proof is the revenue assertion above, a straight sum
    # a naive "average the two summaries" implementation would get wrong
    # for any two businesses of different sizes.
    assert combined.gross_margin.gross_margin_pct == parent_only.gross_margin.gross_margin_pct


# --- get_retail_operations_for_group -------------------------------------


def test_group_retail_operations_combines_stock_and_top_sellers_across_businesses(db_session, group):
    parent, branch = group
    product_a = _seed_sales(db_session, parent.id, revenue_multiplier=1)
    product_b = _seed_sales(db_session, branch.id, revenue_multiplier=1)

    combined = get_retail_operations_for_group(
        db_session, businesses=[parent, branch], start_date=_PERIOD_START, end_date=_PERIOD_END
    )
    parent_only = get_retail_operations(db_session, business_id=parent.id, start_date=_PERIOD_START, end_date=_PERIOD_END)
    branch_only = get_retail_operations(db_session, business_id=branch.id, start_date=_PERIOD_START, end_date=_PERIOD_END)

    # Both products present, kept as distinct rows despite the same name.
    ids_in_combined = {row.product_id for row in combined.top_sellers_by_units}
    assert ids_in_combined == {product_a.id, product_b.id}
    # Inventory value at cost sums exactly like revenue did above.
    assert combined.inventory_value.value_at_cost == (
        parent_only.inventory_value.value_at_cost + branch_only.inventory_value.value_at_cost
    )


# --- get_workshop_performance_for_group -----------------------------------


def test_group_workshop_performance_sums_repair_revenue(db_session, group):
    parent, branch = group
    _make_repair(
        db_session, parent.id, completed_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        price_charged=Decimal("50.00"), labour_cost=Decimal("20.00"),
    )
    _make_repair(
        db_session, branch.id, completed_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
        price_charged=Decimal("30.00"), labour_cost=Decimal("10.00"),
    )
    db_session.commit()

    combined = get_workshop_performance_for_group(
        db_session, businesses=[parent, branch], start_date=_PERIOD_START, end_date=_PERIOD_END
    )
    assert combined.revenue.current == Decimal("80.00")
    assert combined.margin.repair_count == 2
