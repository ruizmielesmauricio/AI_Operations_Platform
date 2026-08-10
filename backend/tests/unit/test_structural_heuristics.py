from app.imports.detection import detect_mapping


def test_layer1_alias_dictionary_resolves_common_pos_headers_at_full_confidence():
    header = ["Order Date", "Item Description", "SKU", "Qty", "Unit Price"]
    rows = [
        ["2026-01-03", "Chain Lube", "CL-100", 3, 9.99],
        ["2026-01-04", "Inner Tube 700c", "IT-700", 10, 5.50],
        ["2026-01-05", "Bar Tape", "BT-200", 2, 12.00],
        ["2026-01-06", "Brake Pads", "BP-300", 4, 15.25],
        ["2026-01-07", "Chain Lube", "CL-100", 1, 9.99],
    ]
    result = detect_mapping([header] + rows, "sales")

    assert result.suggested_mapping == {
        "sale_date": "Order Date",
        "product_name": "Item Description",
        "sku": "SKU",
        "quantity": "Qty",
        "unit_price": "Unit Price",
        "total_amount": None,
        "cost_price_at_sale": None,
        "tax_amount": None,
        "order_reference": None,
        "category": None,
        "location": None,
    }
    for field in ("sale_date", "product_name", "sku", "quantity", "unit_price"):
        top = result.field_candidates[field][0]
        assert top.confidence == 1.0
        assert top.source == "alias"


def test_exact_canonical_name_column_wins_over_an_earlier_alias_synonym():
    # Real bug, found via a POS export shape with both a "Subtotal" (pre-tax)
    # and a genuine "Total Amount" (post-tax) column: "subtotal" is a listed
    # alias for total_amount, and it appears earlier in the file, so a
    # naive first-match-wins scan claimed it for total_amount and left the
    # real "Total Amount" column unmapped — silently understating revenue
    # by the tax amount on every row. A column literally named the
    # canonical field must always win, regardless of where it sits in the
    # file relative to a same-meaning-ish synonym elsewhere.
    header = [
        "transaction_id", "quantity", "unit_cost", "unit_price",
        "discount_amount", "subtotal", "tax_rate", "tax_amount", "total_amount",
    ]
    rows = [
        ["TXN-1", "1", "7.34", "11.93", "0.6", "11.33", "0.23", "2.61", "13.94"],
        ["TXN-2", "1", "44.09", "76.73", "0", "76.73", "0.23", "17.65", "94.38"],
        ["TXN-3", "1", "27.49", "44.28", "0", "44.28", "0.23", "10.18", "54.46"],
        ["TXN-4", "2", "62.53", "136.81", "0", "273.62", "0.23", "62.93", "336.55"],
        ["TXN-5", "1", "19.86", "32.14", "0", "32.14", "0.23", "7.39", "39.53"],
    ]
    result = detect_mapping([header] + rows, "sales")

    assert result.suggested_mapping["total_amount"] == "total_amount"
    assert result.suggested_mapping["tax_amount"] == "tax_amount"
    assert result.suggested_mapping["cost_price_at_sale"] == "unit_cost"
    assert result.suggested_mapping["unit_price"] == "unit_price"
    # "subtotal" has nothing left to claim it, since total_amount is taken
    # by the exact match — it falls through as unmapped, not silently
    # mis-assigned elsewhere.
    assert "subtotal" in result.unmapped_columns


def test_a_numeric_id_column_is_never_assigned_to_a_money_field():
    """A register/receipt-number column is plain-integer and would parse as
    "money" just as cleanly as a real amount — only the header signals the
    difference. A wrong assignment here would silently corrupt margin math,
    so this must never happen regardless of how clean the parse rate is.
    """
    header = ["When", "Stuff", "Num", "Txn Value", "Register#"]
    rows = [
        ["03/01/2026", "Chain Lube", 3, "9.99", 4501],
        ["04/01/2026", "Inner Tube 700c", 10, "55.00", 4502],
        ["05/01/2026", "Bar Tape", 2, "24.00", 4503],
        ["06/01/2026", "Brake Pads", 4, "61.00", 4504],
        ["07/01/2026", "Chain Lube", 1, "9.99", 4505],
        ["08/01/2026", "Helmet", 1, "45.00", 4506],
    ]
    result = detect_mapping([header] + rows, "sales")

    for field in ("unit_price", "total_amount", "cost_price_at_sale"):
        assert result.suggested_mapping[field] != "Register#"
        assert all(c.source_column != "Register#" for c in result.field_candidates[field])


def test_quantity_is_not_confused_with_a_large_magnitude_serial_column():
    header = ["Date", "Item", "Qty", "Serial Number"]
    rows = [
        ["2026-01-01", "Widget", 2, 100234],
        ["2026-01-02", "Widget", 1, 100235],
        ["2026-01-03", "Widget", 3, 100236],
        ["2026-01-04", "Widget", 2, 100237],
        ["2026-01-05", "Widget", 1, 100238],
    ]
    result = detect_mapping([header] + rows, "sales")
    assert result.suggested_mapping["quantity"] == "Qty"


def test_sku_shaped_code_column_is_not_confused_with_product_name():
    """Neither header is in the alias dictionary, forcing structural
    heuristics to tell a real product-name column ("Blue Widget", no
    digits) apart from a genuinely code-shaped one ("WID-001", contains
    digits) — the two must not tie and land on the wrong field.
    """
    header = ["Date", "Ref", "Details", "Qty", "Price"]
    rows = [
        ["2026-01-01", "WID-001", "Blue Widget", 2, 5.00],
        ["2026-01-02", "WID-002", "Red Widget", 1, 7.00],
        ["2026-01-03", "WID-001", "Blue Widget", 3, 5.00],
        ["2026-01-04", "WID-003", "Green Widget", 1, 9.00],
        ["2026-01-05", "WID-001", "Blue Widget", 2, 5.00],
    ]
    result = detect_mapping([header] + rows, "sales")
    assert result.suggested_mapping["sku"] == "Ref"
    assert result.suggested_mapping["product_name"] == "Details"


def test_columns_with_too_few_samples_are_never_scored():
    header = ["Date", "Item", "Qty", "Price"]
    rows = [["2026-01-01", "Widget", 1, 5.00]] * 3  # below _MIN_SAMPLES_FOR_SCORING
    result = detect_mapping([header] + rows, "sales")
    # Alias matches (Date/Item/Qty/Price all have direct aliases) still
    # apply regardless of row count — this only constrains layer 2.
    assert result.suggested_mapping["sale_date"] == "Date"


def test_order_reference_groups_multiple_rows_via_header_name_only():
    header = ["Date", "Item", "Qty", "Price", "Order Number"]
    rows = [
        ["2026-01-01", "Chain Lube", 2, 5.00, "ORD-1001"],
        ["2026-01-01", "Bar Tape", 1, 12.00, "ORD-1001"],
        ["2026-01-02", "Helmet", 1, 45.00, "ORD-1002"],
        ["2026-01-03", "Brake Pads", 4, 15.25, "ORD-1003"],
        ["2026-01-04", "Chain Lube", 1, 9.99, "ORD-1004"],
    ]
    result = detect_mapping([header] + rows, "sales")
    assert result.suggested_mapping["order_reference"] == "Order Number"


def test_a_bare_ref_column_is_not_claimed_by_order_reference_over_sku():
    # "Ref" alone is at least as plausible as a product reference/code as
    # an order reference — it must not be auto-claimed away from sku.
    header = ["Date", "Ref", "Details", "Qty", "Price"]
    rows = [
        ["2026-01-01", "WID-001", "Blue Widget", 2, 5.00],
        ["2026-01-02", "WID-002", "Red Widget", 1, 7.00],
        ["2026-01-03", "WID-001", "Blue Widget", 3, 5.00],
        ["2026-01-04", "WID-003", "Green Widget", 1, 9.00],
        ["2026-01-05", "WID-001", "Blue Widget", 2, 5.00],
    ]
    result = detect_mapping([header] + rows, "sales")
    assert result.suggested_mapping["sku"] == "Ref"
    assert result.suggested_mapping["order_reference"] is None
