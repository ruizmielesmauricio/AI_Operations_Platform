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
