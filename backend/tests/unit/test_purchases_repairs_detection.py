from app.imports.detection import detect_mapping


def test_clean_purchases_export_resolves_via_alias():
    header = ["Date", "Product", "SKU", "Qty Received", "Unit Cost"]
    rows = [
        ["2026-01-0" + str(i % 9 + 1), "Chain Lube", "CL-100", str(10 + i), str(4.5 + i * 0.1)]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "purchases")
    assert result.suggested_mapping == {
        "purchase_date": "Date",
        "product_name": "Product",
        "sku": "SKU",
        "quantity_received": "Qty Received",
        "unit_cost": "Unit Cost",
    }


def test_quantity_received_structural_fallback_beats_a_competing_po_number_column():
    # "PO Number" is small-integer-shaped too — quantity_received must not
    # be confused with it, and a bulk restock quantity must not be
    # penalized the way sales' "quantity" field penalizes large values.
    header = ["Received", "Item", "Code", "PO Number", "Units Received"]
    rows = [
        ["2026-01-0" + str(i + 1), "Chain Lube", "CL-100", 1000 + i, 250 + i * 10]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "purchases")
    assert result.suggested_mapping["quantity_received"] == "Units Received"


def test_unit_cost_with_no_token_signal_is_capped_below_high_confidence():
    header = ["Date", "Product", "SKU", "Amount"]
    rows = [
        ["2026-01-0" + str(i + 1), "Chain Lube", "CL-100", str(4.5 + i)]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "purchases")
    candidates = result.field_candidates["unit_cost"]
    assert candidates
    assert candidates[0].confidence <= 0.6


def test_clean_repairs_export_resolves_via_alias():
    header = ["Repair Date", "Description", "Price Charged", "Labour Cost"]
    rows = [
        ["2026-01-0" + str(i + 1), "Replaced brake pads", str(45 + i), str(20 + i)]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "repairs")
    assert result.suggested_mapping == {
        "repair_date": "Repair Date",
        "description": "Description",
        "price_charged": "Price Charged",
        "labour_cost": "Labour Cost",
    }


def test_repair_date_and_purchase_date_reuse_the_same_date_heuristic_as_sale_date():
    # Both fall through to the generalized date-parseability branch —
    # confirms the sale_date branch's generalization didn't break anything
    # entity-specific for the new fields.
    purchase_header = ["Date", "Product", "SKU", "Qty Received"]
    purchase_rows = [["2026-01-0" + str(i + 1), "Chain Lube", "CL-100", str(10 + i)] for i in range(6)]
    purchase_result = detect_mapping([purchase_header] + purchase_rows, "purchases")
    assert purchase_result.suggested_mapping["purchase_date"] == "Date"

    repair_header = ["Date", "Description"]
    repair_rows = [["2026-01-0" + str(i + 1), "Fixed a puncture"] for i in range(6)]
    repair_result = detect_mapping([repair_header] + repair_rows, "repairs")
    assert repair_result.suggested_mapping["repair_date"] == "Date"
