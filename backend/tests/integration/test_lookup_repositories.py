"""Covers the three new per-record search/lookup repository methods that
back ORLA's product_lookup/purchase_lookup/repair_lookup chat intents
(app/ai/service.py, app/application/lookups.py) — 0/1/many-match cases
against a real (SQLite) database, each new method in isolation."""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductRepository
from app.repositories.production_event import ProductionEventRepository


def _make_product(db_session, business_id, *, name, sku=None, cost_price=None, sell_price=None):
    return ProductRepository(db_session).create(
        business_id=business_id, sku=sku, name=name, cost_price=cost_price, sell_price=sell_price
    )


# --- ProductRepository.search_by_name_or_sku -----------------------------


def test_search_by_name_or_sku_matches_a_substring_of_the_name_case_insensitively(db_session, business_id):
    product = _make_product(db_session, business_id, name="Chain Lube 100ml", sku="CL-100")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(business_id, "chain lube")
    assert [p.id for p in results] == [product.id]


def test_search_by_name_or_sku_matches_an_exact_normalized_sku(db_session, business_id):
    product = _make_product(db_session, business_id, name="Bottle Cage", sku="bc-42")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(business_id, "BC-42")
    assert [p.id for p in results] == [product.id]


def test_search_by_name_or_sku_does_not_fuzzy_match_a_partial_sku(db_session, business_id):
    _make_product(db_session, business_id, name="Bottle Cage", sku="BC-42")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(business_id, "BC-4")
    assert results == []


def test_search_by_name_or_sku_returns_no_matches_for_an_unknown_query(db_session, business_id):
    _make_product(db_session, business_id, name="Chain Lube")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(business_id, "Bottom Bracket")
    assert results == []


def test_search_by_name_or_sku_matches_its_own_disambiguation_label_format(db_session, business_id):
    # Real bug, found live: app/application/lookups.py's many-match
    # message formats each option as "name (sku)" — a user naturally
    # copies one of those labels back verbatim, which previously matched
    # neither the plain name substring nor the exact sku (the combined
    # string is neither), returning zero results.
    product = _make_product(db_session, business_id, name="WorkshopPro Lubricant Plus", sku="SKU-00175")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(
        business_id, "WorkshopPro Lubricant Plus (SKU-00175)"
    )
    assert [p.id for p in results] == [product.id]


def test_search_by_name_or_sku_with_trailing_paren_still_matches_on_name_alone(db_session, business_id):
    # The parenthetical doesn't have to be a real sku for the name half
    # to still resolve — e.g. a size/variant annotation a user added
    # themselves that happens to not match anything.
    product = _make_product(db_session, business_id, name="Chain Lube", sku="CL-100")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(business_id, "Chain Lube (100ml)")
    assert [p.id for p in results] == [product.id]


def test_search_by_name_or_sku_returns_every_match_when_several_share_a_word(db_session, business_id):
    a = _make_product(db_session, business_id, name="Chain Lube 100ml")
    b = _make_product(db_session, business_id, name="Chain Lube 250ml")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(business_id, "chain lube")
    assert {p.id for p in results} == {a.id, b.id}


def test_search_by_name_or_sku_is_scoped_to_the_business(db_session, business_id):
    from app.models.business import Business

    other_business = Business(name="Other Business")
    db_session.add(other_business)
    db_session.commit()

    _make_product(db_session, other_business.id, name="Chain Lube")
    db_session.commit()

    results = ProductRepository(db_session).search_by_name_or_sku(business_id, "chain lube")
    assert results == []


# --- InventoryMovementRepository.list_purchases ---------------------------


def test_list_purchases_matches_a_purchase_reference_case_insensitively_and_by_substring(db_session, business_id):
    product = _make_product(db_session, business_id, name="Chain Lube")
    db_session.commit()
    InventoryMovementRepository(db_session).create(
        business_id=business_id, product_id=product.id, quantity_delta=10, reason="purchase",
        purchase_reference="PO-123-ABC", event_date=date(2026, 6, 1),
    )
    db_session.commit()

    results = InventoryMovementRepository(db_session).list_purchases(business_id, purchase_reference="po-123")
    assert len(results) == 1
    assert results[0].purchase_reference == "PO-123-ABC"


def test_list_purchases_filters_by_date_range(db_session, business_id):
    product = _make_product(db_session, business_id, name="Chain Lube")
    db_session.commit()
    repo = InventoryMovementRepository(db_session)
    repo.create(
        business_id=business_id, product_id=product.id, quantity_delta=5, reason="purchase",
        purchase_reference="PO-1", event_date=date(2026, 1, 1),
    )
    repo.create(
        business_id=business_id, product_id=product.id, quantity_delta=5, reason="purchase",
        purchase_reference="PO-2", event_date=date(2026, 6, 15),
    )
    db_session.commit()

    results = repo.list_purchases(business_id, start=date(2026, 6, 1), end=date(2026, 6, 30))
    assert [m.purchase_reference for m in results] == ["PO-2"]


def test_list_purchases_never_returns_a_sale_or_adjustment_movement(db_session, business_id):
    product = _make_product(db_session, business_id, name="Chain Lube")
    db_session.commit()
    repo = InventoryMovementRepository(db_session)
    repo.create(business_id=business_id, product_id=product.id, quantity_delta=-1, reason="sale", event_date=date(2026, 6, 1))
    repo.create(
        business_id=business_id, product_id=product.id, quantity_delta=0, reason="adjustment",
        resulting_quantity_on_hand=10, event_date=date(2026, 6, 1),
    )
    db_session.commit()

    results = repo.list_purchases(business_id)
    assert results == []


def test_list_purchases_returns_empty_when_nothing_matches(db_session, business_id):
    results = InventoryMovementRepository(db_session).list_purchases(business_id, purchase_reference="NOPE")
    assert results == []


# --- ProductionEventRepository.find_repairs -------------------------------


def _make_repair(db_session, business_id, *, repair_reference=None, description=None, opened_at, price_charged=None, labour_cost=None):
    return ProductionEventRepository(db_session).create(
        business_id=business_id, event_type="repair", description=description, status="completed",
        opened_at=opened_at, completed_at=opened_at, labour_cost=labour_cost, price_charged=price_charged,
        customer_id=None, performed_by_id=None, import_record_id=None, repair_reference=repair_reference,
    )


def test_find_repairs_matches_a_repair_reference_case_insensitively_and_by_substring(db_session, business_id):
    _make_repair(
        db_session, business_id, repair_reference="JOB-364", opened_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        price_charged=Decimal("89.99"),
    )
    db_session.commit()

    results = ProductionEventRepository(db_session).find_repairs(business_id, repair_reference="job-364")
    assert len(results) == 1
    assert results[0].price_charged == Decimal("89.99")


def test_find_repairs_falls_back_to_description_when_no_reference_given(db_session, business_id):
    _make_repair(
        db_session, business_id, description="Brake pad replacement", opened_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    db_session.commit()

    results = ProductionEventRepository(db_session).find_repairs(business_id, description_contains="brake pad")
    assert len(results) == 1


def test_find_repairs_only_matches_event_type_repair_not_production(db_session, business_id):
    ProductionEventRepository(db_session).create(
        business_id=business_id, event_type="production", description="Batch build",
        status="completed", opened_at=datetime(2026, 6, 1, tzinfo=timezone.utc), completed_at=None,
        labour_cost=None, price_charged=None, customer_id=None, performed_by_id=None,
        import_record_id=None, repair_reference="JOB-999",
    )
    db_session.commit()

    results = ProductionEventRepository(db_session).find_repairs(business_id, repair_reference="JOB-999")
    assert results == []


def test_find_repairs_filters_by_opened_at_range(db_session, business_id):
    _make_repair(db_session, business_id, repair_reference="JAN", opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _make_repair(db_session, business_id, repair_reference="JUN", opened_at=datetime(2026, 6, 15, tzinfo=timezone.utc))
    db_session.commit()

    results = ProductionEventRepository(db_session).find_repairs(
        business_id, start=datetime(2026, 6, 1, tzinfo=timezone.utc), end=datetime(2026, 7, 1, tzinfo=timezone.utc)
    )
    assert [r.repair_reference for r in results] == ["JUN"]


def test_find_repairs_returns_every_match_when_several_share_a_description(db_session, business_id):
    _make_repair(db_session, business_id, description="Full service", opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _make_repair(db_session, business_id, description="Full service", opened_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    db_session.commit()

    results = ProductionEventRepository(db_session).find_repairs(business_id, description_contains="full service")
    assert len(results) == 2
