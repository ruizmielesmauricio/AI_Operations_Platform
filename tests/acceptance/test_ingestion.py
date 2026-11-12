"""Schema-agnostic ingestion — AC-020..AC-031 (criteria §4)."""

import re
import uuid
from datetime import date
from decimal import Decimal

from conftest import FIXTURES, auth, csv_bytes, xlsx_bytes

BASIC = [
    ["Date", "Product", "SKU", "Qty", "Unit Price"],
    ["2026-01-02", "Chain Lube", "CL-1", "3", "9.99"],
    ["2026-01-03", "Bar Tape", "BT-1", "1", "12.00"],
    ["2026-01-04", "Inner Tube", "IT-1", "5", "6.50"],
]
EXPECTED_BASIC = {
    ("2026-01-02", "Chain Lube", 3, Decimal("9.99")),
    ("2026-01-03", "Bar Tape", 1, Decimal("12.00")),
    ("2026-01-04", "Inner Tube", 5, Decimal("6.50")),
}


def _stored(orla, user, biz_id):
    return {
        (r["sold_at"][:10], r["product_name"], int(r["quantity"]), Decimal(str(r["unit_price"])))
        for r in orla.sales(user, biz_id)
    }


def _summary_messages(result) -> list[str]:
    summary = result.get("rejection_summary") or {}
    msgs = []
    for group in ("reasons", "excluded", "warnings"):
        for entry in (summary.get(group) or {}).values():
            msgs.append(entry["message"])
    return msgs


def _summary_count(result, *groups) -> int:
    summary = result.get("rejection_summary") or {}
    return sum(entry["count"] for g in groups for entry in (summary.get(g) or {}).values())


def test_formats_and_column_order(orla):
    """AC-020: CSV, XLS, XLSX, and a column-shuffled CSV all store identical rows."""
    from datetime import datetime

    xlsx_rows = [BASIC[0]] + [
        [datetime.strptime(r[0], "%Y-%m-%d"), r[1], r[2], int(r[3]), float(r[4])] for r in BASIC[1:]
    ]
    order = [3, 1, 4, 0, 2]
    shuffled = [[row[i] for i in order] for row in BASIC]
    variants = {
        "sales.csv": csv_bytes(BASIC),
        "sales.xlsx": xlsx_bytes(xlsx_rows),
        "sales.xls": (FIXTURES / "sales_basic.xls").read_bytes(),
        "shuffled.csv": csv_bytes(shuffled),
    }
    for i, (name, content) in enumerate(variants.items()):
        user = f"fmt-{i}"
        biz = orla.create_business(user)
        result = orla.import_file(user, biz["id"], name, content)
        assert result["rows_imported"] == 3, f"{name}: imported {result['rows_imported']}"
        assert _stored(orla, user, biz["id"]) == EXPECTED_BASIC, f"{name} stored different data"


def test_header_detection_with_junk_rows(orla):
    """AC-021: header found beneath up to 10 junk rows."""
    junk = [
        ["SALES REPORT"], ["Store: Main Street"], [], ["Generated: 05/01/2026 09:14"], ["Period", "Jan 2026"],
        [], ["Printed by: admin"], ["Page 1 of 1"], [], ["Confidential"],
    ]
    biz = orla.create_business("junk-user")
    upload = orla.start_upload("junk-user", biz["id"], "report.csv", csv_bytes(junk + BASIC))
    detected = orla.detect("junk-user", biz["id"], upload)
    assert detected["status"] != "header_not_found"
    assert detected["columns"][:5] == BASIC[0]
    orla.confirm("junk-user", biz["id"], upload, detected["suggested_mapping"])
    assert orla.run_import("junk-user", biz["id"], upload)["rows_imported"] == 3


def test_known_aliases_auto_map(orla):
    """AC-022: common product-name headers map with no user input."""
    biz = orla.create_business("alias-user")
    for header in ("Item", "Product", "Description", "Product Name", "SKU Description"):
        content = csv_bytes([["Date", header, "Qty", "Price"], ["2026-01-02", "Widget", "1", "5.00"]])
        upload = orla.start_upload("alias-user", biz["id"], f"{header}.csv", content)
        detected = orla.detect("alias-user", biz["id"], upload)
        assert detected["suggested_mapping"].get("product_name") == header, f"{header!r} not auto-mapped"
        assert detected["suggested_mapping"].get("sale_date") == "Date"


def test_unmatched_column_plain_language_prompt(orla):
    """AC-023. Contract: when a required field can't be confidently matched,
    detect-mapping returns `questions`: [{"field", "prompt": "Which column is
    the <plain name>?", "options": [{"column", "sample_values": [3 values]}]}]."""
    content = csv_bytes([
        ["Field1", "Field2", "Field3", "Field4"],
        ["02/01/2026", "Widget", "1", "5.00"],
        ["03/01/2026", "Gadget", "2", "7.50"],
        ["04/01/2026", "Doohickey", "3", "2.25"],
        ["05/01/2026", "Thing", "4", "1.10"],
    ])
    biz = orla.create_business("q-user")
    upload = orla.start_upload("q-user", biz["id"], "opaque.csv", content)
    detected = orla.detect("q-user", biz["id"], upload)
    assert detected["status"] == "needs_confirmation"
    questions = detected.get("questions")
    assert questions, "no plain-language questions returned for unconfirmed fields"
    fields = {q["field"] for q in questions}
    assert "sale_date" in fields
    for q in questions:
        assert re.fullmatch(r"Which column is the [a-z ]+\?", q["prompt"]), q["prompt"]
        assert "_" not in q["prompt"], "technical field names must not be shown"
        assert q["options"]
        for opt in q["options"]:
            assert len(opt["sample_values"]) == 3
    date_q = next(q for q in questions if q["field"] == "sale_date")
    field1 = next(o for o in date_q["options"] if o["column"] == "Field1")
    assert field1["sample_values"] == ["02/01/2026", "03/01/2026", "04/01/2026"]


def test_saved_mapping_reused(orla):
    """AC-024: second upload from the same source needs zero mapping input."""
    biz = orla.create_business("reuse-user")
    header = ["Txn Dt", "Item Desc", "Units", "Each"]
    orla.import_file("reuse-user", biz["id"], "a.csv", csv_bytes([header, ["2026-01-02", "W", "1", "5.00"]]),
                     mapping={"sale_date": "Txn Dt", "product_name": "Item Desc", "quantity": "Units",
                              "unit_price": "Each"})
    upload = orla.start_upload("reuse-user", biz["id"], "b.csv", csv_bytes([header, ["2026-01-03", "G", "2", "7.00"]]))
    detected = orla.detect("reuse-user", biz["id"], upload)
    assert detected["status"] == "reused"
    assert {k: v for k, v in detected["suggested_mapping"].items() if v} == {
        "sale_date": "Txn Dt", "product_name": "Item Desc", "quantity": "Units", "unit_price": "Each"}


def test_format_normalisation(orla):
    """AC-025: dates, currency, separators, decimal commas, whitespace and case
    normalised without asking. Ambiguous day/month order is inferred from the
    file's unambiguous dates, else day-first; contract: the import result
    carries `date_order` ("day_first" | "month_first" | "iso")."""
    cases = [
        ("dmy.csv", [["Date", "Product", "Qty", "Price"],
                     ["13/01/26", "  chain LUBE  ", "1", "€1,234.50"],
                     ["03/02/26", "Bar Tape", "2", "€ 10.00"]],
         {("2026-01-13", Decimal("1234.50")), ("2026-02-03", Decimal("10.00"))}, "day_first"),
        ("mdy.csv", [["Date", "Product", "Qty", "Price"],
                     ["01-13-2026", "Chain Lube", "1", "1.234,50 €"],
                     ["02-03-2026", "Bar Tape", "2", "10,00"]],
         {("2026-01-13", Decimal("1234.50")), ("2026-02-03", Decimal("10.00"))}, "month_first"),
        ("ambiguous.csv", [["Date", "Product", "Qty", "Price"],
                           ["03/04/26", "Chain Lube", "1", "5.00"],
                           ["05/06/26", "Bar Tape", "1", "6.00"]],
         {("2026-04-03", Decimal("5.00")), ("2026-06-05", Decimal("6.00"))}, "day_first"),
        ("iso.csv", [["Date", "Product", "Qty", "Price"],
                     ["2026-02-03", "Chain Lube", "1", "EUR 7.25"]],
         {("2026-02-03", Decimal("7.25"))}, "iso"),
    ]
    for i, (name, rows, expected, order) in enumerate(cases):
        user = f"norm-{i}"
        biz = orla.create_business(user)
        result = orla.import_file(user, biz["id"], name, csv_bytes(rows))
        assert result["rows_rejected"] == 0, f"{name}: rejected rows {result.get('rejection_summary')}"
        stored = {(r["sold_at"][:10], Decimal(str(r["unit_price"]))) for r in orla.sales(user, biz["id"])}
        assert stored == expected, f"{name}: stored {stored}"
        assert result.get("date_order") == order, f"{name}: date_order {result.get('date_order')!r}"
    names = {r["product_name"] for r in orla.sales("norm-0", orla.client.get(
        "/businesses", headers=auth("norm-0")).json()[0]["id"])}
    assert "Chain Lube" in names or "chain LUBE" in names, f"whitespace not trimmed: {names}"
    assert not any(n != n.strip() for n in names)


MESSY = [
    ["Date", "Product", "Qty", "Unit Price"],
    ["2026-01-02", "Chain Lube", "3", "9.99"],
    ["", "", "", ""],
    ["2026-01-03", "Bar Tape", "1", "12.00"],
    ["Subtotal", "", "4", "41.97"],
    ["Date", "Product", "Qty", "Unit Price"],
    ["2026-01-04", "Inner Tube", "5", "6.50"],
    ["Total", "", "9", "74.47"],
    ["Generated by TillPoint POS v4.2", "", "", ""],
]


def test_messy_rows_excluded(orla):
    """AC-026: blank, subtotal, repeated-header, footer and note rows (and a
    merged title cell in XLSX) are excluded; only real sales are stored."""
    for i, (name, content) in enumerate([
        ("messy.csv", csv_bytes(MESSY)),
        ("messy.xlsx", xlsx_bytes([["Weekly sales export", None, None, None]] + MESSY, merge="A1:D1")),
    ]):
        user = f"messy-{i}"
        biz = orla.create_business(user)
        result = orla.import_file(user, biz["id"], name, content)
        names = sorted(r["product_name"] for r in orla.sales(user, biz["id"]))
        assert names == ["Bar Tape", "Chain Lube", "Inner Tube"], f"{name}: stored {names}"
        assert result["rows_imported"] == 3


def test_every_row_accounted_for(orla):
    """AC-027: rows_imported + every categorised exclusion == every non-blank
    row under the header; each category has a plain-language message."""
    rows = MESSY + [
        ["", "Saddle", "1", "30.00"],
        ["", "Pedals", "1", "25.00"],
        ["2026-01-05", "Bell", "lots", "4.00"],
    ]
    biz = orla.create_business("count-user")
    result = orla.import_file("count-user", biz["id"], "count.csv", csv_bytes(rows))
    non_blank_below_header = sum(1 for r in rows[1:] if any(str(c).strip() for c in r))
    accounted = result["rows_imported"] + _summary_count(result, "reasons", "excluded")
    assert accounted == non_blank_below_header, (
        f"{non_blank_below_header} rows in file, only {accounted} accounted for: {result.get('rejection_summary')}"
    )
    msgs = _summary_messages(result)
    assert any(re.search(r"2 rows? skipped: .*date", m, re.I) for m in msgs), msgs
    for m in msgs:
        assert not re.search(r"Traceback|Exception|Error:|\b[a-z]+_[a-z_]+\b", m), f"not plain language: {m!r}"


def test_file_deleted_after_import(orla):
    """AC-028: the uploaded file is removed from object storage once imported."""
    from app.models.upload import Upload

    biz = orla.create_business("del-user")
    result = orla.import_file("del-user", biz["id"], "s.csv", csv_bytes(BASIC))
    with orla.session() as s:
        key = s.get(Upload, uuid.UUID(result["_upload_id"])).storage_key
    assert key in orla.r2.deleted and key not in orla.r2.objects


def _stock(orla, user, biz_id, name):
    r = orla.client.get(f"/businesses/{biz_id}/products/thresholds", headers=auth(user))
    assert r.status_code == 200, r.text
    rows = r.json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    return next(p["stock_on_hand"] for p in rows if p["name"] == name)


def test_undo_restores_prior_state(orla):
    """AC-029: undoing an import restores sales and stock exactly."""
    biz = orla.create_business("undo-user")
    from datetime import timedelta

    orla.import_file("undo-user", biz["id"], "restock.csv", csv_bytes([
        ["Date", "Product", "SKU", "Qty Received"],
        [(date.today() - timedelta(days=2)).isoformat(), "Chain Lube", "CL-1", "10"],
    ]), entity_type="purchases")
    before_stock = _stock(orla, "undo-user", biz["id"], "Chain Lube")
    sales = orla.import_file("undo-user", biz["id"], "s.csv", csv_bytes([
        ["Date", "Product", "SKU", "Qty", "Unit Price"],
        [date.today().isoformat(), "Chain Lube", "CL-1", "3", "9.99"],
    ]))
    assert _stock(orla, "undo-user", biz["id"], "Chain Lube") == before_stock - 3
    undo = orla.client.post(
        f"/businesses/{biz['id']}/import-records/{sales['import_record_id']}/undo", headers=auth("undo-user")
    )
    assert undo.status_code == 200
    assert orla.sales("undo-user", biz["id"]) == []
    assert _stock(orla, "undo-user", biz["id"], "Chain Lube") == before_stock


def test_import_idempotent_and_transactional(orla, monkeypatch):
    """AC-030: re-importing the same file adds nothing; a failure part-way
    leaves no partial rows (fault injected after the first rows are written)."""
    biz = orla.create_business("idem-user")
    orla.import_file("idem-user", biz["id"], "s.csv", csv_bytes(BASIC))
    orla.import_file("idem-user", biz["id"], "s-again.csv", csv_bytes(BASIC))
    assert len(orla.sales("idem-user", biz["id"])) == 3, "the same file imported twice double-counted sales"

    from app.imports import importer

    biz2 = orla.create_business("tx-user")
    original = importer.ProductMatcher.register_created
    calls = {"n": 0}

    def fail_on_third(self, product):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("injected failure mid-import")
        return original(self, product)

    monkeypatch.setattr(importer.ProductMatcher, "register_created", fail_on_third)
    upload = orla.start_upload("tx-user", biz2["id"], "s.csv", csv_bytes(BASIC))
    detected = orla.detect("tx-user", biz2["id"], upload)
    orla.confirm("tx-user", biz2["id"], upload, detected["suggested_mapping"])
    try:
        orla.client.post(f"/businesses/{biz2['id']}/uploads/{upload}/import", headers=auth("tx-user"))
    except Exception:
        pass
    monkeypatch.setattr(importer.ProductMatcher, "register_created", original)
    assert calls["n"] >= 3, "fault was never reached; the test could not exercise a mid-import failure"
    from app.models.product import Product
    from app.models.sale import Sale

    with orla.session() as s:
        assert s.query(Sale).filter(Sale.business_id == uuid.UUID(biz2["id"])).count() == 0
        assert s.query(Product).filter(Product.business_id == uuid.UUID(biz2["id"])).count() == 0


def test_customer_pii_not_imported(orla):
    """AC-031: customer name/email/phone in an upload are never stored."""
    biz = orla.create_business("pii-user")
    orla.import_file("pii-user", biz["id"], "pii.csv", csv_bytes([
        ["Date", "Product", "Qty", "Unit Price", "Customer Name", "Customer Email", "Phone"],
        ["2026-01-02", "Chain Lube", "1", "9.99", "Siobhan Kowalczyk", "siobhan.k@example.ie", "+353871234567"],
    ]))
    from sqlalchemy import String, Text, select

    from app.models import Base

    with orla.session() as s:
        for table in Base.metadata.sorted_tables:
            text_cols = [c for c in table.c if isinstance(c.type, (String, Text))]
            for col in text_cols:
                for (value,) in s.execute(select(col)).all():
                    if value and any(p in str(value) for p in ("Kowalczyk", "siobhan.k@", "871234567")):
                        raise AssertionError(f"customer PII stored in {table.name}.{col.name}")
