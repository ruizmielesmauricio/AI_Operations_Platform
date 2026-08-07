from decimal import Decimal

from app.ai.guardrail import extract_numeric_claims, flatten_numeric_values, validate_grounded


def test_extract_numeric_claims_finds_money_percent_and_plain_numbers():
    text = "Revenue was €4,758.24, up 12.0%, across 59 transactions."
    claims = extract_numeric_claims(text)
    assert "4,758.24" in claims
    assert "12.0%" in claims
    assert "59" in claims


def test_flatten_numeric_values_reads_native_ints_and_decimal_strings():
    context = {"transactions": 59, "revenue": {"current": "4758.24"}, "low_stock_count": 3}
    values = flatten_numeric_values(context)
    assert Decimal("59") in values
    assert Decimal("4758.24") in values
    assert Decimal("3") in values


def test_flatten_numeric_values_recurses_into_lists():
    context = {"top_products": [{"revenue": "100.00"}, {"revenue": "250.50"}]}
    values = flatten_numeric_values(context)
    assert Decimal("100.00") in values
    assert Decimal("250.50") in values


def test_flatten_numeric_values_excludes_booleans():
    context = {"grounded": True, "count": 0}
    values = flatten_numeric_values(context)
    assert Decimal("1") not in values
    assert Decimal("0") in values  # the count, not the bool


def test_validate_grounded_passes_when_every_number_traces_to_context():
    context = {"revenue": {"current": "4758.24", "change_pct": "12.0"}, "transactions": 59}
    answer = "Revenue was €4,758.24 this period, up 12.0% across 59 transactions."
    result = validate_grounded(answer, context)
    assert result.grounded is True
    assert result.unsupported_claims == []


def test_validate_grounded_rejects_an_invented_number():
    context = {"revenue": {"current": "4758.24"}}
    answer = "Revenue was €9,999.99 this period."
    result = validate_grounded(answer, context)
    assert result.grounded is False
    assert "9,999.99" in result.unsupported_claims


def test_validate_grounded_ignores_trailing_zero_formatting_differences():
    # Decimal("39.9") == Decimal("39.90") — a phrasing difference, not a
    # different number, must not be flagged.
    context = {"gross_margin_pct": "39.90"}
    answer = "Gross margin was 39.9%."
    result = validate_grounded(answer, context)
    assert result.grounded is True


def test_validate_grounded_does_not_match_a_rounded_figure():
    # Deliberately strict: rounding €11,907.76 to €11,908 is a different
    # number as far as the guardrail is concerned — fail closed.
    context = {"revenue": {"current": "11907.76"}}
    answer = "Revenue was about €11,908."
    result = validate_grounded(answer, context)
    assert result.grounded is False


def test_validate_grounded_accepts_the_unsigned_form_of_a_negative_context_value():
    # Live-verified this is a real scenario, not theoretical: a model
    # naturally phrases a decline as "down 35.7%," not "-35.7%" — the
    # same convention app/analytics/report_narrative.py already uses
    # (abs(change_pct) + the word "decreased").
    context = {"revenue": {"change_pct": "-35.7"}}
    answer = "Revenue was down 35.7% compared with the previous period."
    result = validate_grounded(answer, context)
    assert result.grounded is True


def test_validate_grounded_accepts_a_number_embedded_in_a_product_name():
    # Live-verified real bug: "CityRoll MTB 200" is a product NAME, not a
    # numeric field — the guardrail must still recognise "200" as
    # grounded when the AI repeats the name verbatim, not just when a
    # field is purely numeric.
    context = {"findings": [{"evidence": {"name": "CityRoll MTB 200", "stock_on_hand": 0}}]}
    answer = "CityRoll MTB 200 is out of stock."
    result = validate_grounded(answer, context)
    assert result.grounded is True


def test_validate_grounded_ignores_digits_embedded_in_a_uuid():
    # A UUID's digit runs are structurally meaningless — they must not
    # get treated as "allowed" numbers, or the guardrail would let real
    # invented figures slip through by coincidence.
    context = {"product_id": "7b289c43-7576-4272-a330-4a069b275df6"}
    answer = "You sold 7576 units this period."
    result = validate_grounded(answer, context)
    assert result.grounded is False


def test_validate_grounded_skips_non_numeric_text():
    context = {"revenue": {"current": "100.00"}}
    answer = "Revenue looked healthy this period."
    result = validate_grounded(answer, context)
    assert result.grounded is True
    assert result.unsupported_claims == []
