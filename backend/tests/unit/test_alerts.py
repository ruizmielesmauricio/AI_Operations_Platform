from decimal import Decimal

from app.application.alerts import _jsonable_evidence


def test_jsonable_evidence_converts_decimal_to_str_and_leaves_everything_else():
    evidence = {
        "product_id": "abc-123",
        "name": "Chain Lube",
        "stock_on_hand": 5,
        "cover_days": Decimal("2.00"),
        "revenue_in_period": Decimal("50.00"),
        "threshold_days": Decimal("7"),
    }

    result = _jsonable_evidence(evidence)

    assert result == {
        "product_id": "abc-123",
        "name": "Chain Lube",
        "stock_on_hand": 5,
        "cover_days": "2.00",
        "revenue_in_period": "50.00",
        "threshold_days": "7",
    }
    # Every value is now a plain JSON-serializable type — no Decimal left.
    import json

    json.dumps(result)
