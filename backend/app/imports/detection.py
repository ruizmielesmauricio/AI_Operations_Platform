"""The schema/column detection engine (B7, PR-2.2-2.5).

Layering, cheapest/most-deterministic first: alias dictionary (layer 1,
app/imports/aliases.py) -> structural heuristics on sampled values (layer
2, below) -> anything left is returned as a candidate list for the user to
confirm (PR-2.4). No AI layer yet — Stage E's AI gateway doesn't exist,
and the FieldCandidate.source field already reserves room for a future
"ai" value without a contract change.

Pure functions only: no file/network/DB I/O. app/imports/service.py owns
reading the file (file_parser.py) and persisting the result.
"""

import hashlib
import re
import statistics
from dataclasses import dataclass, field as dataclass_field

from app.imports.aliases import CANONICAL_FIELDS, match_alias, normalize_header
from app.imports.exceptions import HeaderRowNotFound, InvalidHeaderRowIndex, UnsupportedEntityType
from app.imports.file_parser import normalize_cell
from app.imports.value_parsers import parse_date, parse_int, parse_money

Row = list[object]

_HEADER_SEARCH_WINDOW = 15
_HEADER_LOOKAHEAD_ROWS = 5
_MIN_HEADER_SCORE = 9.0  # ~53% of the theoretical max of 17

_STRUCTURAL_SAMPLE_SIZE = 200
_MIN_SAMPLES_FOR_SCORING = 5
_HIGH_CONFIDENCE = 0.85
_MIN_CONFIDENCE = 0.5
_CANDIDATES_PER_FIELD = 3

_MONEY_FIELDS = ("unit_price", "total_amount", "cost_price_at_sale")
_MONEY_TOKENS = {
    "unit_price": {"price", "unit", "each", "rate"},
    "total_amount": {"total", "amount", "grand", "net", "sum", "revenue", "subtotal"},
    "cost_price_at_sale": {"cost", "cogs"},
}
_SKU_TOKENS = {"sku", "code", "barcode", "upc"}
# Deliberately excludes bare "ref": a column just called "Ref" is at least
# as likely to mean a product reference/code as an order reference — too
# ambiguous to claim on its own (confirmed by testing: it was winning the
# column away from "sku" for exactly this reason).
_ORDER_REFERENCE_TOKENS = {"order", "receipt", "transaction", "txn", "invoice", "reference"}
# An inventory file commonly has other integer-shaped columns competing
# for this (reorder point, bin/aisle number, row id) — unlike sales'
# quantity field, which rarely shares a file with another small-integer
# column, so a bare parse-rate score is not enough signal on its own here.
_QUANTITY_ON_HAND_TOKENS = {"stock", "inventory", "onhand", "hand", "qty", "count"}
# Requires at least one digit (lookahead) rather than stripping spaces and
# checking alnum shape alone — a plain product-name word ("Blue Widget")
# is otherwise indistinguishable from a real code once spaces are removed.
# Real SKUs/codes almost always contain a digit; ordinary product-name
# words almost never do.
_SKU_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9\- ]{1,19}$")

# A register/receipt/row-number column is plain-integer and so parses as
# "money" just as cleanly as a real amount does — nothing in the value
# itself distinguishes them, only the header. Scoped to money fields only
# (not quantity: "Num"/"Number" are common, legitimate quantity-column
# names, whereas nobody names a price/amount column "Number" or "ID") and
# deliberately excludes "transaction"/"txn" (ambiguous — "Transaction
# Amount" is a real money-field header, not an identifier one). A bare
# numeric ID column must never fill a money field, which would silently
# corrupt every margin figure computed from it — hence a veto, not a
# reduced score.
_IDENTIFIER_HEADER_RE = re.compile(r"\b(id|no|num|number|reg|register|receipt)\b|#")


def _looks_like_identifier_header(header_norm: str) -> bool:
    return bool(_IDENTIFIER_HEADER_RE.search(header_norm))


@dataclass
class FieldCandidate:
    source_column: str
    confidence: float
    source: str  # "alias" | "structural"
    sample_values: list[str]


@dataclass
class DetectionResult:
    header_row_index: int
    columns: list[str]
    suggested_mapping: dict[str, str | None]
    field_candidates: dict[str, list[FieldCandidate]] = dataclass_field(default_factory=dict)
    unmapped_columns: list[str] = dataclass_field(default_factory=list)
    source_signature: str = ""


def compute_source_signature(entity_type: str, columns: list[str]) -> str:
    """Order-independent (PR-2.1: any column order) but duplicate-count
    sensitive (PR-2.7: duplicate headers mid-file are a real case — deduping
    would wrongly collide a file with one "Description" column with one
    that has two).
    """
    normalized = sorted(h for h in (normalize_header(c) for c in columns) if h)
    payload = entity_type + "|" + "|".join(normalized)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detect_mapping(grid: list[Row], entity_type: str) -> DetectionResult:
    """Auto-detects the header row, then maps its columns. Raises
    HeaderRowNotFound if no row scores confidently enough — the caller
    decides whether to surface that as a hard failure or fall back to
    detect_mapping_with_header() once the user's picked the row by hand."""
    if entity_type not in CANONICAL_FIELDS:
        raise UnsupportedEntityType(entity_type)
    header_row_index = detect_header_row(grid, entity_type)
    return detect_mapping_with_header(grid, entity_type, header_row_index)


def detect_mapping_with_header(grid: list[Row], entity_type: str, header_row_index: int) -> DetectionResult:
    """Same mapping logic as detect_mapping(), but skips auto-detection —
    used both internally and for the manual header-row picker fallback
    (PR-2.2's "let the user point at it" escape hatch)."""
    if entity_type not in CANONICAL_FIELDS:
        raise UnsupportedEntityType(entity_type)
    if not (0 <= header_row_index < len(grid)):
        raise InvalidHeaderRowIndex(header_row_index, len(grid))

    header_row = grid[header_row_index]
    data_rows = grid[header_row_index + 1 :]
    columns = [normalize_cell(c) for c in header_row]
    fields = CANONICAL_FIELDS[entity_type]

    column_for_field: dict[str, int] = {}
    field_for_column: dict[int, str] = {}
    field_candidates: dict[str, list[FieldCandidate]] = {f: [] for f in fields}

    # Layer 1: alias dictionary — deterministic, first matching column wins.
    for col_idx, header in enumerate(columns):
        if not header:
            continue
        matched_field = match_alias(header, entity_type)
        if matched_field and matched_field not in column_for_field:
            column_for_field[matched_field] = col_idx
            field_for_column[col_idx] = matched_field
            field_candidates[matched_field].append(
                FieldCandidate(
                    source_column=header,
                    confidence=1.0,
                    source="alias",
                    sample_values=_sample_display_values(data_rows, col_idx),
                )
            )

    # Layer 2: structural heuristics on whatever layer 1 left unresolved.
    remaining_fields = [f for f in fields if f not in column_for_field]
    remaining_cols = [i for i, h in enumerate(columns) if h and i not in field_for_column]

    scored: list[tuple[float, int, str]] = []
    per_field_scores: dict[str, list[tuple[float, int]]] = {f: [] for f in remaining_fields}
    for col_idx in remaining_cols:
        samples = _column_samples(data_rows, col_idx)
        header_norm = normalize_header(columns[col_idx])
        for f in remaining_fields:
            score = _score_field(f, samples, header_norm)
            if score > 0:
                per_field_scores[f].append((score, col_idx))
                if score >= _MIN_CONFIDENCE:
                    scored.append((score, col_idx, f))

    scored.sort(key=lambda t: t[0], reverse=True)
    for score, col_idx, f in scored:
        if col_idx in field_for_column or f in column_for_field:
            continue
        column_for_field[f] = col_idx
        field_for_column[col_idx] = f

    for f in remaining_fields:
        ranked = sorted(per_field_scores[f], key=lambda t: t[0], reverse=True)[:_CANDIDATES_PER_FIELD]
        field_candidates[f] = [
            FieldCandidate(
                source_column=columns[col_idx],
                confidence=round(score, 2),
                source="structural",
                sample_values=_sample_display_values(data_rows, col_idx),
            )
            for score, col_idx in ranked
        ]

    suggested_mapping = {
        f: columns[column_for_field[f]] if f in column_for_field else None for f in fields
    }
    unmapped_columns = [
        columns[i] for i in range(len(columns)) if columns[i] and i not in field_for_column
    ]

    return DetectionResult(
        header_row_index=header_row_index,
        columns=columns,
        suggested_mapping=suggested_mapping,
        field_candidates=field_candidates,
        unmapped_columns=unmapped_columns,
        source_signature=compute_source_signature(entity_type, columns),
    )


def detect_header_row(grid: list[Row], entity_type: str) -> int:
    max_candidate = min(_HEADER_SEARCH_WINDOW - 1, len(grid) - 1)
    if max_candidate < 0:
        raise HeaderRowNotFound()

    best_index: int | None = None
    best_score = float("-inf")
    for i in range(max_candidate + 1):
        score = _score_header_candidate(grid, i, entity_type)
        # >= (not >) on a tie deliberately picks the larger index: a row
        # that ties with an earlier one is more likely that earlier row was
        # a section title, not a second, equally-good header.
        if score >= best_score:
            best_score = score
            best_index = i

    if best_index is None or best_score < _MIN_HEADER_SCORE:
        raise HeaderRowNotFound()
    return best_index


def _score_header_candidate(grid: list[Row], i: int, entity_type: str) -> float:
    cells = grid[i]
    non_blank_idx = [j for j, c in enumerate(cells) if normalize_cell(c) != ""]
    if len(non_blank_idx) < 2:
        return float("-inf")

    non_blank_raw = [cells[j] for j in non_blank_idx]
    non_blank_norm = [normalize_cell(c) for c in non_blank_raw]

    fill_ratio = len(non_blank_idx) / len(cells)
    uniqueness_ratio = len(set(non_blank_norm)) / len(non_blank_norm)

    parseable = sum(1 for c in non_blank_raw if _looks_like_data_value(c))
    string_ratio = 1 - (parseable / len(non_blank_raw))

    alias_hits = sum(1 for c in non_blank_norm if match_alias(c, entity_type) is not None)
    alias_hit_ratio = alias_hits / len(non_blank_norm)

    below_rows = [
        r for r in grid[i + 1 : i + 1 + _HEADER_LOOKAHEAD_ROWS] if any(normalize_cell(c) != "" for c in r)
    ]
    if below_rows:
        numeric_cols = 0
        for j in non_blank_idx:
            if any(j < len(r) and _looks_like_data_value(r[j]) for r in below_rows):
                numeric_cols += 1
        below_numeric_ratio = numeric_cols / len(non_blank_idx)

        below_widths = [sum(1 for c in r if normalize_cell(c) != "") for r in below_rows]
        mode_width = statistics.mode(below_widths)
        denom = max(len(non_blank_idx), mode_width, 1)
        width_consistency = 1 - abs(len(non_blank_idx) - mode_width) / denom
    else:
        below_numeric_ratio = 0.0
        width_consistency = 0.0

    return (
        3 * fill_ratio
        + 3 * uniqueness_ratio
        + 2 * string_ratio
        + 4 * alias_hit_ratio
        + 3 * below_numeric_ratio
        + 2 * width_consistency
    )


def _looks_like_data_value(value: object) -> bool:
    return parse_date(value) is not None or parse_money(value) is not None or parse_int(value) is not None


def _column_samples(data_rows: list[Row], col_idx: int, limit: int = _STRUCTURAL_SAMPLE_SIZE) -> list[object]:
    samples = []
    for row in data_rows:
        if col_idx >= len(row):
            continue
        value = row[col_idx]
        if normalize_cell(value) == "":
            continue
        samples.append(value)
        if len(samples) >= limit:
            break
    return samples


def _sample_display_values(data_rows: list[Row], col_idx: int, limit: int = 3) -> list[str]:
    return [normalize_cell(v) for v in _column_samples(data_rows, col_idx, limit=limit)]


def _token_overlap(header_norm: str, tokens: set[str]) -> float:
    return 1.0 if set(header_norm.split()) & tokens else 0.0


def _score_field(field: str, samples: list[object], header_norm: str) -> float:
    if len(samples) < _MIN_SAMPLES_FOR_SCORING:
        return 0.0
    if field == "sale_date":
        return sum(1 for v in samples if parse_date(v) is not None) / len(samples)
    if field == "quantity":
        parsed = [parse_int(v) for v in samples]
        valid = [p for p in parsed if p is not None]
        if not valid:
            return 0.0
        rate = len(valid) / len(samples)
        magnitude_penalty = 0.5 if statistics.median(valid) > 1000 else 1.0
        return rate * magnitude_penalty
    if field == "quantity_on_hand":
        # Unlike "quantity" (a sales line-item count, rarely competing with
        # another small integer column), an inventory file commonly has
        # reorder points, bin numbers, or row ids also parsing as clean
        # integers — so this needs the money-fields' name-signal treatment,
        # not a bare parse rate. No magnitude penalty: a warehouse stock
        # count can legitimately be in the thousands.
        parsed = [parse_int(v) for v in samples]
        valid = [p for p in parsed if p is not None]
        if not valid:
            return 0.0
        rate = len(valid) / len(samples)
        token_bonus = _token_overlap(header_norm, _QUANTITY_ON_HAND_TOKENS)
        if token_bonus == 0.0:
            return 0.6 * rate
        return 0.7 * rate + 0.3 * token_bonus
    if field in _MONEY_FIELDS:
        if _looks_like_identifier_header(header_norm):
            return 0.0
        parsed = [parse_money(v) for v in samples]
        valid = [p for p in parsed if p is not None]
        money_rate = len(valid) / len(samples)
        token_bonus = _token_overlap(header_norm, _MONEY_TOKENS[field])
        # A wrong money-field assignment silently corrupts every margin
        # number downstream, so with zero name signal this is capped well
        # below the auto-assign threshold regardless of how clean the
        # parse rate looks.
        if token_bonus == 0.0:
            return 0.6 * money_rate
        return 0.7 * money_rate + 0.3 * token_bonus
    if field == "product_name":
        texts = [
            normalize_cell(v)
            for v in samples
            if isinstance(v, str) and parse_date(v) is None and parse_money(v) is None
        ]
        text_ratio = len(texts) / len(samples)
        if not texts:
            return 0.0
        cardinality = len(set(texts)) / len(texts)
        cardinality_score = 1.0 if 0.05 <= cardinality <= 0.6 else 0.4
        avg_len = sum(len(t) for t in texts) / len(texts)
        length_score = 1.0 if 3 <= avg_len <= 60 else 0.5
        score = text_ratio * 0.5 + cardinality_score * 0.3 + length_score * 0.2
        # Without this, a genuinely code-shaped column ("WID-001") can tie a
        # real name column at the same score — nothing above otherwise
        # penalizes code-like text, so it reads as equally "name-shaped."
        # This is the product_name/sku mirror of the identifier-header
        # exclusion above: a shape that looks like a code is evidence
        # *against* it being the product name, not neutral.
        sku_like_rate = sum(1 for t in texts if _SKU_RE.match(t)) / len(texts)
        return score * (1 - 0.5 * sku_like_rate)
    if field == "sku":
        texts = [normalize_cell(v) for v in samples]
        regex_rate = sum(1 for t in texts if _SKU_RE.match(t)) / len(texts)
        token_bonus = _token_overlap(header_norm, _SKU_TOKENS)
        return 0.5 * regex_rate + 0.5 * token_bonus
    if field == "order_reference":
        # Order/receipt/transaction ids come in every shape (numeric,
        # alphanumeric, with or without punctuation) — there's no reliable
        # value-shape signal the way there is for dates or money. The
        # header name is the only real evidence, so this is deliberately
        # token-only: a matching name is a full-confidence signal, no name
        # match is no signal at all (never guessed from values alone).
        return 1.0 if _token_overlap(header_norm, _ORDER_REFERENCE_TOKENS) else 0.0
    return 0.0
