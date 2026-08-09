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
        "purchase_reference": None,
        "category": None,
        "location": None,
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


def test_purchase_order_id_alias_resolves_purchase_reference():
    # Real bug, found via Gate B testing with synthetic_orders.csv: none
    # of purchase_order_id/supplier_order_reference/supplier_invoice_number
    # matched anything in the alias list (exact-string match only, no
    # fuzzy/substring matching), so purchase_reference came back with
    # zero candidates and needed a manual pick every time.
    header = ["Order Date", "Product", "SKU", "Qty Received", "Unit Cost", "Purchase Order Id"]
    rows = [
        ["2026-01-0" + str(i % 9 + 1), "Chain Lube", "CL-100", str(10 + i), str(4.5 + i * 0.1), f"PO-{1000 + i}"]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "purchases")
    assert result.suggested_mapping["purchase_reference"] == "Purchase Order Id"


def test_issue_description_alias_resolves_over_a_weaker_notes_column():
    # Real bug, found via Gate B testing with synthetic_repairs.csv: the
    # actual repair description lived in "Issue Description", but only
    # "notes" (frequently empty in real exports) was in the alias list —
    # it won purely because nothing else was offered, silently mapping
    # description to the weaker, often-blank field instead.
    header = ["Repair Date", "Issue Description", "Notes", "Price Charged", "Labour Cost"]
    rows = [
        ["2026-01-0" + str(i + 1), "Wheel out of true", "", str(45 + i), str(20 + i)]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "repairs")
    assert result.suggested_mapping["description"] == "Issue Description"


def test_total_amount_and_labour_amount_aliases_resolve_directly():
    # Real bug, found via Gate B testing with synthetic_repairs.csv: a
    # two-word "Total Amount"/"Labour Amount" header matched neither the
    # single-word "amount"/"total" alias entries nor (before this fix)
    # won their structural tie — now resolved directly via alias, no
    # ambiguity to break at all.
    header = ["Repair Date", "Description", "Total Amount", "Labour Amount"]
    rows = [
        ["2026-01-0" + str(i + 1), "Fixed a puncture", f"{100.00 + i:.2f}", f"{45.00 + i:.2f}"]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "repairs")
    assert result.suggested_mapping["price_charged"] == "Total Amount"
    assert result.suggested_mapping["labour_cost"] == "Labour Amount"


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
        "tax_amount": None,
        "repair_reference": None,
        "location": None,
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
