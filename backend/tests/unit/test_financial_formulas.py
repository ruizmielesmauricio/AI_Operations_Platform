

def test_average_sale_is_revenue_over_sale_count_rounded_to_the_cent():
    from decimal import Decimal
    from app.analytics.financial import compute_average_sale

    assert compute_average_sale(Decimal("100.00"), 3) == Decimal("33.33")
    assert compute_average_sale(Decimal("100.01"), 2) == Decimal("50.01")  # half-up, not banker's
    assert compute_average_sale(Decimal("0"), 5) == Decimal("0.00")
    assert compute_average_sale(Decimal("50"), 0) is None
