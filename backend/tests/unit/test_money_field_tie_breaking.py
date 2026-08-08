"""Regression coverage for the money-field tie-breaking fix (Gate B
finding: uploading a real synthetic_repairs.csv, B7 confidently picked
labour_amount over the correct total_amount for price_charged, and
labour_hours — an hours-worked column, not a cost — over labour_amount
for labour_cost. Root cause: when multiple structural candidates tied at
the exact same score, the previous "leftmost column in the file wins"
tiebreak silently picked one with full apparent confidence.

These tests deliberately use header names that don't match any
aliases.py entry, so they exercise the structural layer (detection.py's
_score_field money branch + the tie-exclusion pass) directly, not the
alias fix (covered separately in test_purchases_repairs_detection.py).
"""

from app.imports.detection import detect_mapping


def test_hours_shaped_values_lose_to_currency_shaped_values_for_a_money_field():
    # An hours-worked column parses as cleanly as a currency column
    # (parse_money doesn't care about decimal places) — only genuine
    # 2-decimal-place formatting actually tells them apart structurally.
    header = ["Date", "Description", "Labour Duration", "Labour Fee"]
    rows = [
        ["2026-01-0" + str(i + 1), "Fixed a puncture", str(2 + i * 0.5), f"{50.00 + i:.2f}"]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "repairs")
    assert result.suggested_mapping["labour_cost"] == "Labour Fee"


def test_a_genuine_money_field_tie_is_left_unmapped_not_guessed():
    # Two equally-plausible, equally currency-shaped columns for the same
    # field — a wrong guess here would silently corrupt every margin
    # figure computed from it, so this must come back unmapped, not
    # resolved by whichever column happens to sit first in the file.
    header = ["Date", "Description", "Labour Fee", "Labour Payment"]
    rows = [
        ["2026-01-0" + str(i + 1), "Fixed a puncture", f"{50.00 + i:.2f}", f"{45.00 + i:.2f}"]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "repairs")
    assert result.suggested_mapping["labour_cost"] is None
    candidates = {c.source_column for c in result.field_candidates["labour_cost"]}
    assert candidates == {"Labour Fee", "Labour Payment"}
    # Real candidates, not hidden — a human reviewing this file sees both
    # options at genuine confidence, not a false single "top pick".
    assert all(c.confidence >= 0.5 for c in result.field_candidates["labour_cost"])


def test_a_multi_token_match_beats_a_single_token_match_for_a_money_field():
    # The old binary token-overlap (any match at all = full credit)
    # couldn't distinguish a weak single-token match ("Repair Amount"
    # matching only "amount") from a strong multi-token one ("Total
    # Invoice" matching both "total" and "invoice") — both scored
    # identically. Proportional overlap now correctly separates them,
    # resolving what used to be an accidental tie.
    header = ["Date", "Description", "Total Invoice", "Repair Amount"]
    rows = [
        ["2026-01-0" + str(i + 1), "Fixed a puncture", f"{100.00 + i:.2f}", f"{45.00 + i:.2f}"]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "repairs")
    assert result.suggested_mapping["price_charged"] == "Total Invoice"


def test_a_non_money_field_still_resolves_normally_with_only_one_candidate():
    # Regression guard: the tie-exclusion pass only fires when a money
    # field genuinely has two-or-more close candidates — a single clean
    # candidate must still auto-resolve exactly as before.
    header = ["Date", "Description", "Labour Fee"]
    rows = [
        ["2026-01-0" + str(i + 1), "Fixed a puncture", f"{50.00 + i:.2f}"]
        for i in range(6)
    ]
    result = detect_mapping([header] + rows, "repairs")
    assert result.suggested_mapping["labour_cost"] == "Labour Fee"
