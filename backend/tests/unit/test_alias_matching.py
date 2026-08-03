from app.imports.aliases import match_alias, normalize_header


def test_normalize_header_is_case_whitespace_and_punctuation_insensitive():
    variants = {normalize_header(h) for h in ["Sale Date", "sale_date", " Sale-Date ", "SALE.DATE"]}
    assert variants == {"sale date"}


def test_pr_2_3_s_literal_alias_example_all_resolve_to_product_name():
    # The exact example set from docs/governance/10_Product_Requirements.md PR-2.3.
    for header in ["Item", "Product", "Description", "Product Name", "SKU Description"]:
        assert match_alias(header, "sales") == "product_name"


def test_sale_date_aliases():
    for header in ["Date", "Sale Date", "Transaction Date", "Order Date", "Invoice Date"]:
        assert match_alias(header, "sales") == "sale_date"


def test_quantity_price_and_sku_aliases():
    assert match_alias("Qty", "sales") == "quantity"
    assert match_alias("Unit Price", "sales") == "unit_price"
    assert match_alias("Total Amount", "sales") == "total_amount"
    assert match_alias("Cost Price", "sales") == "cost_price_at_sale"
    assert match_alias("SKU", "sales") == "sku"


def test_order_reference_aliases():
    for header in ["Order Number", "Receipt Number", "Transaction ID", "Invoice Number"]:
        assert match_alias(header, "sales") == "order_reference"


def test_register_number_is_never_an_order_reference_alias():
    # A till/register number identifies the terminal, not the transaction —
    # grouping by it would merge unrelated sales together.
    assert match_alias("Register Number", "sales") is None
    assert match_alias("Register#", "sales") is None


def test_unmatched_header_returns_none():
    assert match_alias("Random Column XYZ", "sales") is None


def test_blank_header_returns_none():
    assert match_alias("", "sales") is None
    assert match_alias("   ", "sales") is None


def test_no_customer_pii_fields_are_mappable():
    # Data-minimisation constraint: customer name/email/phone must never be
    # a canonical field the engine will suggest mapping anything onto.
    from app.imports.aliases import CANONICAL_FIELDS

    assert not any("customer" in f or "email" in f or "phone" in f for f in CANONICAL_FIELDS["sales"])
