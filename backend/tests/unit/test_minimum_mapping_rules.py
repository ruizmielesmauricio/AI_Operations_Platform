from app.imports.aliases import MINIMUM_MAPPING_RULES


def test_sales_requires_date_and_a_price_field():
    rule = MINIMUM_MAPPING_RULES["sales"]
    assert rule({"sale_date": "Date", "unit_price": "Price"})
    assert rule({"sale_date": "Date", "total_amount": "Total"})
    assert not rule({"sale_date": "Date"})
    assert not rule({"unit_price": "Price"})


def test_inventory_requires_an_identifier_and_a_quantity():
    rule = MINIMUM_MAPPING_RULES["inventory"]
    assert rule({"sku": "SKU", "quantity_on_hand": "Stock"})
    assert rule({"product_name": "Product", "quantity_on_hand": "Stock"})
    assert not rule({"sku": "SKU"})  # no quantity
    assert not rule({"quantity_on_hand": "Stock"})  # no identifier
    assert not rule({})
    # unit_cost is never required
    assert rule({"sku": "SKU", "quantity_on_hand": "Stock", "unit_cost": None})


def test_purchases_requires_date_identifier_and_quantity():
    rule = MINIMUM_MAPPING_RULES["purchases"]
    assert rule({"purchase_date": "Date", "sku": "SKU", "quantity_received": "Qty"})
    assert rule({"purchase_date": "Date", "product_name": "Product", "quantity_received": "Qty"})
    assert not rule({"sku": "SKU", "quantity_received": "Qty"})  # no date
    assert not rule({"purchase_date": "Date", "quantity_received": "Qty"})  # no identifier
    assert not rule({"purchase_date": "Date", "sku": "SKU"})  # no quantity
    # unit_cost is never required
    assert rule({"purchase_date": "Date", "sku": "SKU", "quantity_received": "Qty", "unit_cost": None})


def test_repairs_requires_date_and_one_detail_field():
    rule = MINIMUM_MAPPING_RULES["repairs"]
    assert rule({"repair_date": "Date", "description": "Notes"})
    assert rule({"repair_date": "Date", "price_charged": "Price"})
    assert rule({"repair_date": "Date", "labour_cost": "Labour"})
    assert not rule({"repair_date": "Date"})  # no detail at all
    assert not rule({"description": "Notes"})  # no date
    assert not rule({})
