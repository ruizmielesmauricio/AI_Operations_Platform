"""Dashboards, analytics, findings, forecasts, alerts, agent — AC-059..AC-070 (criteria §8)."""

import json
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal

from conftest import SALES_HEADER, auth, csv_bytes

JAN = {"start": "2026-01-01", "end": "2026-01-31"}


def _get(orla, user, biz_id, path, **params):
    r = orla.client.get(f"/businesses/{biz_id}/analytics/{path}", params=params, headers=auth(user))
    assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"
    return r.json()


def _jan_shop(orla, user="calc-user", with_cost=True):
    biz = orla.create_business(user)
    orla.import_file(user, biz["id"], "restock.csv", csv_bytes([
        ["Date", "Product", "SKU", "Qty Received", "Unit Cost"],
        ["2025-12-20", "Alpha", "A", "100", "2.00"],
        ["2025-12-20", "Bravo", "B", "50", "5.00"],
    ]), entity_type="purchases")
    cost_a, cost_b = ("2.00", "5.00") if with_cost else ("", "")
    orla.import_file(user, biz["id"], "jan.csv", csv_bytes([
        SALES_HEADER,
        ["2026-01-10", "Alpha", "A", "10", "5.00", cost_a],
        ["2026-01-12", "Bravo", "B", "4", "12.50", cost_b],
    ]))
    return biz


def test_metrics_deterministic_and_correct(orla):
    """AC-059: revenue, gross margin and stock cover equal hand-computed
    Decimal values, and repeat calls are identical.
    Revenue 10x5.00 + 4x12.50 = 100.00; COGS 10x2 + 4x5 = 40.00;
    gross profit 60.00; margin 60.00%. Alpha stock 100-10 = 90, sold 10 in
    31 days -> cover 90 / (10/31) = 279.00 days."""
    biz = _jan_shop(orla)
    fin = _get(orla, "calc-user", biz["id"], "financial-performance", **JAN)
    assert Decimal(fin["revenue"]["current"]) == Decimal("100.00")
    gm = fin["gross_margin"]
    assert Decimal(gm["cogs"]) == Decimal("40.00")
    assert Decimal(gm["gross_profit"]) == Decimal("60.00")
    assert Decimal(gm["gross_margin_pct"]) == Decimal("60.00")
    retail = _get(orla, "calc-user", biz["id"], "retail-operations", **JAN)
    alpha = next(r for r in retail["stock_cover"] if r["name"] == "Alpha")
    assert (alpha["stock_on_hand"], alpha["units_sold_in_period"]) == (90, 10)
    assert Decimal(alpha["cover_days"]) == Decimal("279.00")
    for path in ("financial-performance", "retail-operations", "findings"):
        assert _get(orla, "calc-user", biz["id"], path, **JAN) == _get(orla, "calc-user", biz["id"], path, **JAN)


def test_money_is_decimal(orla):
    """AC-060: every money column is NUMERIC/Decimal; API money is never a float."""
    from sqlalchemy import Numeric

    from app.models import Base

    money_words = ("price", "cost", "amount", "total", "revenue", "value", "profit")
    problems = []
    for table in Base.metadata.sorted_tables:
        for col in table.c:
            name = col.name
            if not any(w in name for w in money_words) or name.startswith("rows_") or name.endswith(("_count", "_id")):
                continue
            if not isinstance(col.type, Numeric) or not getattr(col.type, "asdecimal", False):
                problems.append(f"{table.name}.{name} is {col.type!r}")
    assert not problems, "\n".join(problems)
    biz = _jan_shop(orla, "dec-user")
    fin = _get(orla, "dec-user", biz["id"], "financial-performance", **JAN)
    assert isinstance(fin["revenue"]["current"], str), "money serialised as a float"


def test_no_profit_without_cost_data(orla):
    """AC-061: with no cost data, no profit or margin figure is returned."""
    biz = _jan_shop(orla, "nocost-user", with_cost=False)
    gm = _get(orla, "nocost-user", biz["id"], "financial-performance", **JAN)["gross_margin"]
    assert Decimal(gm["total_revenue"]) == Decimal("100.00")
    assert gm["gross_profit"] is None, f"profit implied without cost data: {gm['gross_profit']}"
    assert gm["gross_margin_pct"] is None


def test_module_has_five_elements(orla):
    """AC-062. Contract: each module response carries `module_summary` with
    status, trend, drivers (list), risks (list), recommended_action."""
    biz = _jan_shop(orla, "five-user")
    for path in ("financial-performance", "retail-operations"):
        summary = _get(orla, "five-user", biz["id"], path, **JAN).get("module_summary")
        assert summary, f"{path}: no module_summary"
        assert isinstance(summary["status"], str) and summary["status"]
        assert isinstance(summary["trend"], str) and summary["trend"]
        assert isinstance(summary["drivers"], list) and isinstance(summary["risks"], list)
        assert "recommended_action" in summary


def test_partial_data_flagged(orla):
    """AC-063: a metric on partial data says how complete it is."""
    biz = orla.create_business("partial-user")
    orla.import_file("partial-user", biz["id"], "jan.csv", csv_bytes([
        SALES_HEADER,
        ["2026-01-10", "Alpha", "A", "1", "50.00", "20.00"],
        ["2026-01-11", "Bravo", "B", "1", "50.00", ""],
    ]))
    gm = _get(orla, "partial-user", biz["id"], "financial-performance", **JAN)["gross_margin"]
    assert Decimal(gm["cost_data_coverage_pct"]) == Decimal("50.00")
    assert Decimal(gm["gross_margin_pct"]) == Decimal("60.00"), "margin must be computed on the costed half only"


def test_drilldown_paginated_and_capped(orla):
    """AC-064: drill-down lists the real rows behind a figure, paged, with a
    server-side cap that a direct API call can't exceed."""
    biz = orla.create_business("drill-user")
    rows = [SALES_HEADER] + [[f"2026-01-{d:02d}", "Alpha" if d % 2 else "Bravo", "A" if d % 2 else "B", "1", "5.00", "2.00"]
                             for d in range(1, 31)]
    orla.import_file("drill-user", biz["id"], "s.csv", csv_bytes(rows))
    h = auth("drill-user")
    over = orla.client.get(f"/businesses/{biz['id']}/transactions/sales", params={"limit": 100000}, headers=h)
    assert over.status_code == 422, "page size cap not enforced server-side"
    all_rows = orla.sales("drill-user", biz["id"])
    assert len(all_rows) == 30
    alpha_id = next(r["product_id"] for r in all_rows if r["product_name"] == "Alpha")
    alpha = orla.sales("drill-user", biz["id"], product_id=alpha_id)
    assert len(alpha) == 15 and {r["product_name"] for r in alpha} == {"Alpha"}
    p1 = orla.client.get(f"/businesses/{biz['id']}/transactions/sales", params={"limit": 10, "offset": 0}, headers=h).json()
    p2 = orla.client.get(f"/businesses/{biz['id']}/transactions/sales", params={"limit": 10, "offset": 10}, headers=h).json()
    items = lambda b: b["items"] if isinstance(b, dict) else b
    assert len(items(p1)) == 10 and not {r["id"] for r in items(p1)} & {r["id"] for r in items(p2)}
    assert all(r.get("import_record_id") for r in all_rows), "rows must trace back to their source upload"


def test_findings_and_recommendations_traceable(orla):
    """AC-065: findings carry rule id/version; every recommendation maps to a
    finding with evidence; ranked by impact; reproducible. Impact reflects
    need from historical sales (decided 12/11/2026): two products both have
    about 5 days of stock left, one sells 1/day, the other 1 every 5 days —
    the faster seller's recommendation ranks higher."""
    biz = orla.create_business("find-user")
    today = date.today()
    orla.import_file("find-user", biz["id"], "stock.csv", csv_bytes([
        ["Date", "Product", "SKU", "Qty Received", "Unit Cost"],
        [(today - timedelta(days=120)).isoformat(), "Dusty Item", "DI", "40", "10.00"],
        [(today - timedelta(days=60)).isoformat(), "Fast Seller", "FS", "35", "3.00"],
        [(today - timedelta(days=60)).isoformat(), "Slow Seller", "SS", "7", "3.00"],
    ]), entity_type="purchases")
    rows = [SALES_HEADER]
    for d in range(1, 31):
        rows.append([(today - timedelta(days=d)).isoformat(), "Fast Seller", "FS", "1", "9.00", "3.00"])
        if d % 5 == 0:
            rows.append([(today - timedelta(days=d)).isoformat(), "Slow Seller", "SS", "1", "9.00", "3.00"])
    orla.import_file("find-user", biz["id"], "s.csv", csv_bytes(rows))
    f1 = _get(orla, "find-user", biz["id"], "findings")
    assert f1 == _get(orla, "find-user", biz["id"], "findings")
    assert f1["findings"], "fixture with dead and low stock produced no findings"
    types = {f["type"] for f in f1["findings"]}
    for f in f1["findings"]:
        assert f["rule_id"] and isinstance(f["rule_version"], int) and f["rule_version"] >= 1
    recs = f1["recommendations"]
    assert recs
    for r in recs:
        assert r["finding_type"] in types and r["evidence"]
    scores = [Decimal(str(r["impact_score"])) for r in recs]
    assert scores == sorted(scores, reverse=True), "recommendations are not ranked by impact"

    def rank(name):
        for i, r in enumerate(recs):
            if name in json.dumps(r["evidence"]) or name in r["title"] or name in r["description"]:
                return i
        raise AssertionError(f"no recommendation for low-stock product {name!r}")

    assert rank("Fast Seller") < rank("Slow Seller"), "the faster-selling low-stock product must rank higher"


def test_forecast_rules(orla):
    """AC-066: deterministic; every number has low/high; refuses below the
    minimum history instead of inventing a figure."""
    today = date.today()
    thin = orla.create_business("thin-user")
    orla.import_file("thin-user", thin["id"], "s.csv", csv_bytes([SALES_HEADER] + [
        [(today - timedelta(days=d)).isoformat(), "A", "A", "1", "5.00", "2.00"] for d in range(1, 4)
    ]))
    res = _get(orla, "thin-user", thin["id"], "forecast")["revenue"]["result"]
    assert res["insufficient_data"] is True and res["daily"] == []

    rich = orla.create_business("rich-user")
    orla.import_file("rich-user", rich["id"], "s.csv", csv_bytes([SALES_HEADER] + [
        [(today - timedelta(days=d)).isoformat(), "A", "A", str(1 + d % 3), "5.00", "2.00"] for d in range(1, 61)
    ]))
    f1 = _get(orla, "rich-user", rich["id"], "forecast")
    assert f1 == _get(orla, "rich-user", rich["id"], "forecast")
    daily = f1["revenue"]["result"]["daily"]
    assert daily
    for d in daily:
        assert Decimal(d["low"]) <= Decimal(d["point"]) <= Decimal(d["high"])


def _low_stock_shop(orla, user):
    today = date.today()
    biz = orla.create_business(user)
    orla.import_file(user, biz["id"], "restock.csv", csv_bytes([
        ["Date", "Product", "SKU", "Qty Received", "Unit Cost"],
        [(today - timedelta(days=20)).isoformat(), "Brake Pads", "BP", "100", "4.00"],
        [(today - timedelta(days=20)).isoformat(), "Plenty Item", "PI", "500", "1.00"],
    ]), entity_type="purchases")
    orla.import_file(user, biz["id"], "s.csv", csv_bytes([SALES_HEADER] + [
        [(today - timedelta(days=d)).isoformat(), "Brake Pads", "BP", "3", "10.00", "4.00"] for d in range(1, 11)
    ] + [[(today - timedelta(days=1)).isoformat(), "Plenty Item", "PI", "1", "2.00", "1.00"]]))
    rows = orla.client.get(f"/businesses/{biz['id']}/products/thresholds", headers=auth(user)).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    pid = next(p["product_id"] for p in rows if p["name"] == "Brake Pads")
    r = orla.client.patch(f"/businesses/{biz['id']}/products/{pid}/threshold",
                          json={"threshold_days": "14"}, headers=auth(user))
    assert r.status_code == 200, r.text
    orla.import_file(user, biz["id"], "count.csv", csv_bytes([
        ["Product", "SKU", "Stock"], ["Brake Pads", "BP", "6"], ["Plenty Item", "PI", "499"],
    ]), entity_type="inventory")
    return biz, pid


def test_low_stock_alert_on_import(orla):
    """AC-067: an import that drops a product below its threshold raises an
    in-app alert immediately; other products don't alert; nothing is emailed."""
    biz, pid = _low_stock_shop(orla, "alert-user")
    alerts = orla.client.get(f"/businesses/{biz['id']}/alerts", headers=auth("alert-user")).json()
    alerts = alerts["items"] if isinstance(alerts, dict) else alerts
    low = [a for a in alerts if a.get("alert_type") == "low_stock"]
    assert [str(a["product_id"]) for a in low] == [pid]
    assert orla.email.sent == []


def test_agent_low_stock_matches_alerts(orla):
    """AC-068. Contract: the classifier may choose intent "low_stock_alerts";
    the data handed to the AI for that answer is exactly the active alert set."""
    from app.ai.service import ALLOWED_INTENTS

    assert "low_stock_alerts" in ALLOWED_INTENTS
    biz, _ = _low_stock_shop(orla, "agent-user")
    orla.ai.classify = {"intent": "low_stock_alerts", "period": None, "metric": None}
    orla.ai.explain = "Brake Pads are running low."
    r = orla.client.post(f"/businesses/{biz['id']}/ai/chat", json={"question": "What's low on stock?"},
                         headers=auth("agent-user"))
    assert r.status_code == 200 and r.json()["intent"] == "low_stock_alerts"
    explain_ctx = orla.ai.calls[-1]["messages"][0]["content"]
    assert "Brake Pads" in explain_ctx and "Plenty Item" not in explain_ctx


def test_unresolved_support_question_handoff(orla):
    """AC-069. Contract: a support question (classifier intent
    "product_support") with no matching help article returns intent
    "support_handoff", invents nothing, and creates a row in table
    support_requests (business_id, user_id, question, status="open")."""
    from sqlalchemy import MetaData, Table, select

    biz = orla.create_business("help-user")
    orla.ai.classify = {"intent": "product_support", "period": None, "metric": None}
    orla.ai.explain = "Sure! Just click Settings > Integrations > Quantum Sync."
    q = "How do I connect my quantum till integration?"
    r = orla.client.post(f"/businesses/{biz['id']}/ai/chat", json={"question": q}, headers=auth("help-user"))
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "support_handoff"
    assert "Quantum Sync" not in body["answer"]
    table = Table("support_requests", MetaData(), autoload_with=orla.engine)
    with orla.engine.connect() as c:
        rows = c.execute(select(table)).mappings().all()
    assert len(rows) == 1
    row = rows[0]
    assert str(row["business_id"]).replace("-", "") == biz["id"].replace("-", "")
    assert row["user_id"] == "help-user" and row["question"] == q and row["status"] == "open"


def test_privileged_actions_audited(orla, monkeypatch):
    """AC-070: permission, billing and deletion actions each leave an audit
    event. Contract: a role change is recorded with both the previous and the
    new role (e.g. action "employee_role_changed"); any "subscription_*"
    on a webhook status change, "business_deleted"."""
    import hashlib
    import hmac

    from app.billing import client as billing_client
    from app.models.audit_log import AuditLog
    from app.settings.config import get_settings

    s = get_settings()
    secret = "whsec_acceptance_audit"
    monkeypatch.setattr(s, "stripe_webhook_secret", secret)
    monkeypatch.setattr(s, "stripe_employee_seat_price_id", "price_seat_placeholder")
    monkeypatch.setattr(billing_client, "create_checkout_session",
                        lambda **k: type("S", (), {"url": "https://checkout.stripe.com/c/pay/cs_test_a"})())
    monkeypatch.setattr(billing_client, "cancel_subscription", lambda *a, **k: None)

    biz = orla.create_business("audit-owner", subscribe=False)
    h = auth("audit-owner")
    seat = orla.client.post(f"/businesses/{biz['id']}/employee-seats", json={
        "first_name": "Ann", "surname": "Lee", "email": "ann@example.com", "role": "manager"}, headers=h)
    assert seat.status_code == 201, seat.text
    seat_id = seat.json()["employee_seat"]["id"]
    upd = orla.client.patch(f"/businesses/{biz['id']}/employee-seats/{seat_id}",
                            json={"first_name": "Ann", "surname": "Lee", "role": "staff"}, headers=h)
    assert upd.status_code == 200, upd.text

    payload = json.dumps({"id": "evt_audit_1", "object": "event", "type": "customer.subscription.updated",
                          "data": {"object": {"id": "sub_aud", "customer": "cus_aud", "status": "active",
                                              "metadata": {"business_id": biz["id"]},
                                              "items": {"data": [{"current_period_end": int(time.time()) + 9999}]}}}}).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    assert orla.client.post("/billing/webhooks/stripe", content=payload,
                            headers={"stripe-signature": f"t={ts},v1={sig}"}).status_code == 200

    with orla.session() as sess:
        after_webhook = [a.action for a in sess.query(AuditLog).filter(AuditLog.business_id == uuid.UUID(biz["id"]))]
    assert any(a.startswith("subscription_") for a in after_webhook), (
        f"billing status change from the webhook not audited: {after_webhook}")

    deleted = orla.client.delete(f"/businesses/{biz['id']}", headers=h)
    assert deleted.status_code in (200, 204), deleted.text

    with orla.session() as sess:
        events = sess.query(AuditLog).filter(AuditLog.business_id == uuid.UUID(biz["id"])).all()
        actions = [a.action for a in events]
        role_events = [a for a in events if a.target_id == seat_id
                       and {"manager", "staff"} <= {str(v) for v in (a.event_metadata or {}).values()}]
    assert "employee_role_changed" in actions or role_events, (
        f"role change not audited with both old and new role: {[(a.action, a.event_metadata) for a in events]}")
    assert "business_deleted" in actions, f"deletion not audited: {actions}"
