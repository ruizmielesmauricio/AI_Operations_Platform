from app.imports.detection import detect_mapping


def test_clean_inventory_export_resolves_via_alias():
    header = ["Product", "SKU", "Stock Level"]
    rows = [
        ["Chain Lube", "CL-100", "25"],
        ["Bar Tape", "BT-200", "8"],
        ["Inner Tube 700c", "IT-700", "150"],
        ["Helmet", "HM-400", "3"],
        ["Brake Pads", "BP-300", "0"],
    ]
    result = detect_mapping([header] + rows, "inventory")
    assert result.suggested_mapping == {
        "product_name": "Product",
        "sku": "SKU",
        "quantity_on_hand": "Stock Level",
        "unit_cost": None,
        "category": None,
        "as_of_date": None,
        "location": None,
    }


def test_quantity_on_hand_structural_fallback_beats_a_competing_small_integer_column():
    # "Reorder Point" is small-integer-shaped too — quantity_on_hand must
    # not be confused with it, and large stock counts must not be penalized
    # the way sales' "quantity" field penalizes large values.
    header = ["Item", "Code", "Reorder Point", "On Hand"]
    rows = [
        ["Chain Lube", "CL-100", 5, 2500],
        ["Bar Tape", "BT-200", 3, 800],
        ["Inner Tube 700c", "IT-700", 10, 1500],
        ["Helmet", "HM-400", 2, 300],
        ["Brake Pads", "BP-300", 4, 0],
    ]
    result = detect_mapping([header] + rows, "inventory")
    assert result.suggested_mapping["quantity_on_hand"] == "On Hand"
    assert result.suggested_mapping["sku"] == "Code"


def test_quantity_on_hand_with_no_token_signal_is_capped_below_high_confidence():
    header = ["Product", "SKU", "Amount"]
    rows = [
        ["Chain Lube", "CL-100", "25"],
        ["Bar Tape", "BT-200", "8"],
        ["Inner Tube 700c", "IT-700", "150"],
        ["Helmet", "HM-400", "3"],
        ["Brake Pads", "BP-300", "0"],
    ]
    result = detect_mapping([header] + rows, "inventory")
    candidates = result.field_candidates["quantity_on_hand"]
    assert candidates
    assert candidates[0].confidence <= 0.6
