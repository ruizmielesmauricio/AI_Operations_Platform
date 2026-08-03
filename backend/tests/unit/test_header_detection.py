import pytest

from app.imports.detection import detect_header_row
from app.imports.exceptions import HeaderRowNotFound

_HEADER = ["Sale Date", "Product Name", "Quantity", "Unit Price", "Total Amount"]
_DATA_ROWS = [
    ["2026-01-01", "Widget A", 2, 5.00, 10.00],
    ["2026-01-02", "Widget B", 1, 15.00, 15.00],
    ["2026-01-03", "Widget A", 3, 5.00, 15.00],
    ["2026-01-04", "Widget C", 1, 25.00, 25.00],
    ["2026-01-05", "Widget A", 2, 5.00, 10.00],
]


def _grid_with_junk_rows(junk_row_count: int) -> list:
    junk = [["Sales Report"] + [None] * 4 for _ in range(junk_row_count)]
    return junk + [_HEADER] + _DATA_ROWS


def test_finds_header_at_row_zero_with_no_junk_rows():
    assert detect_header_row(_grid_with_junk_rows(0), "sales") == 0


@pytest.mark.parametrize("junk_count", [1, 3, 7, 10])
def test_finds_header_with_junk_rows_above(junk_count):
    # PR-2.2: up to 10 junk/title/blank rows above the real header.
    assert detect_header_row(_grid_with_junk_rows(junk_count), "sales") == junk_count


def test_finds_header_with_blank_rows_interspersed():
    grid = [["Sales Report - Q1"], [None], [None], _HEADER] + _DATA_ROWS
    assert detect_header_row(grid, "sales") == 3


def test_raises_when_no_row_looks_like_a_header():
    grid = [[None, None, None]] * 5
    with pytest.raises(HeaderRowNotFound):
        detect_header_row(grid, "sales")


def test_a_noisy_all_text_data_row_does_not_outscore_the_real_header():
    grid = [
        _HEADER,
        ["2026-01-01", "Note about a return", "n/a", "n/a", "n/a"],
        ["2026-01-02", "Widget B", 1, 15.00, 15.00],
        ["2026-01-03", "Widget A", 3, 5.00, 15.00],
        ["2026-01-04", "Widget C", 1, 25.00, 25.00],
        ["2026-01-05", "Widget A", 2, 5.00, 10.00],
    ]
    assert detect_header_row(grid, "sales") == 0


def test_header_beyond_the_search_window_is_not_found():
    # 14 junk rows puts the header at index 14, outside the 0-14 window
    # (max_candidate = min(14, len-1)) — actually right at the boundary;
    # push one further to confirm it's genuinely out of range.
    grid = _grid_with_junk_rows(20)
    with pytest.raises(HeaderRowNotFound):
        detect_header_row(grid, "sales")
