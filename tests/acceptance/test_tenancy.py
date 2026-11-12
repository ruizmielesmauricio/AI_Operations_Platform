"""Tenancy isolation — AC-001..AC-006 (acceptance/criteria.md §1)."""

import re
import uuid

from conftest import SALES_HEADER, auth, csv_bytes

# Shared-core tables that legitimately have no business_id (the tenant itself,
# identities, and Stripe's global event-dedup ledger).
_NON_TENANT_TABLES = {"businesses", "users", "processed_stripe_events"}

# Routes that are public by design (no bearer token can be sent).
#  - health checks
#  - Stripe webhook (authenticated by Stripe signature instead, AC-045)
#  - business logo GET: rendered via <img src>, which cannot carry a bearer
#    token; returns only an image the owner chose to publish.
_PUBLIC = {
    ("GET", "/health"),
    ("GET", "/health/db"),
    ("POST", "/billing/webhooks/stripe"),
    ("GET", "/businesses/{business_id}/logo"),
}


def _operations(orla):
    spec = orla.app.openapi()
    for path, ops in spec["paths"].items():
        for method in ops:
            if method.upper() in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                yield method.upper(), path


def _fill(path: str, business_id: str) -> str:
    path = path.replace("{business_id}", business_id)
    return re.sub(r"\{[a-z_]+\}", lambda m: str(uuid.uuid4()), path)


def _two_tenants_with_data(orla):
    a = orla.create_business("user-a", "Alpha Cycles")
    b = orla.create_business("user-b", "Bravo Secret Store")
    orla.import_file("user-a", a["id"], "a.csv", csv_bytes([
        SALES_HEADER,
        ["2026-01-05", "Alpha Bell", "AB-1", "2", "10.00", "4.00"],
    ]))
    orla.import_file("user-b", b["id"], "b.csv", csv_bytes([
        SALES_HEADER,
        ["2026-01-05", "Zebra Unicorn Saddle", "ZU-9", "3", "777.77", "100.00"],
    ]))
    return a, b


def test_every_tenant_table_has_business_id(orla):
    """AC-001: every tenant-owned table carries a NOT NULL business_id."""
    from app.models import Base

    problems = []
    for table in Base.metadata.sorted_tables:
        if table.name in _NON_TENANT_TABLES:
            continue
        col = table.c.get("business_id")
        if col is None:
            problems.append(f"{table.name}: no business_id column")
        elif col.nullable:
            problems.append(f"{table.name}: business_id is nullable")
    assert not problems, "Tables not tenant-scoped:\n" + "\n".join(problems)


def test_cross_tenant_access_denied_on_every_route(orla):
    """AC-002: every business-scoped route, enumerated from the live app,
    refuses user A acting on business B and leaks none of B's data."""
    a, b = _two_tenants_with_data(orla)
    leaks = []
    for method, path in _operations(orla):
        if "{business_id}" not in path or (method, path) in _PUBLIC:
            continue
        url = _fill(path, b["id"])
        resp = orla.client.request(method, url, headers=auth("user-a"), json={})
        body = resp.text
        if resp.status_code not in (403, 404):
            leaks.append(f"{method} {path} -> {resp.status_code}")
        elif "Zebra Unicorn Saddle" in body or "Bravo Secret Store" in body or "777.77" in body:
            leaks.append(f"{method} {path} -> body contains business B data")
    assert not leaks, "Cross-tenant access not refused:\n" + "\n".join(leaks)


def test_forged_business_id_rejected(orla):
    """AC-003: a business_id smuggled in query/body on A's own route is ignored
    — A only ever reads and writes A."""
    a, b = _two_tenants_with_data(orla)
    h = auth("user-a")

    fin = orla.client.get(
        f"/businesses/{a['id']}/analytics/financial-performance",
        params={"business_id": b["id"], "start": "2026-01-01", "end": "2026-01-31"},
        headers=h,
    )
    assert fin.status_code == 200, fin.text
    assert "777.77" not in fin.text and "2333.31" not in fin.text, "B's revenue leaked via forged query param"

    sup = orla.client.post(
        f"/businesses/{a['id']}/suppliers",
        json={"name": "Forged Supplier Ltd", "business_id": b["id"]},
        headers=h,
    )
    assert sup.status_code in (200, 201, 403, 422), sup.text
    from app.models.supplier import Supplier

    with orla.session() as s:
        in_b = s.query(Supplier).filter(
            Supplier.business_id == uuid.UUID(b["id"]), Supplier.name == "Forged Supplier Ltd"
        ).count()
    assert in_b == 0, "A wrote a supplier into business B via a forged body business_id"

    tx = orla.client.get(
        f"/businesses/{a['id']}/transactions/sales", params={"business_id": b["id"]}, headers=h
    )
    assert tx.status_code == 200
    assert "Zebra Unicorn Saddle" not in tx.text


def test_unauthenticated_requests_rejected(orla):
    """AC-004: every non-public route answers 401 with no token."""
    biz = orla.create_business("owner-x")
    wrong = []
    for method, path in _operations(orla):
        if (method, path) in _PUBLIC or path.startswith(("/docs", "/redoc", "/openapi")):
            continue
        resp = orla.client.request(method, _fill(path, biz["id"]), json={})
        if resp.status_code != 401:
            wrong.append(f"{method} {path} -> {resp.status_code}")
    assert not wrong, "Routes not requiring authentication:\n" + "\n".join(wrong)


def test_ai_context_is_tenant_scoped(orla):
    """AC-005: the context ORLA sends to the AI for business A contains none of
    business B's data, and the AI usage is logged under A."""
    a, b = _two_tenants_with_data(orla)
    orla.ai.classify = {"intent": "retail_operations", "period": "default_recent", "metric": None}
    orla.ai.explain = "Your top seller is Alpha Bell."
    resp = orla.client.post(
        f"/businesses/{a['id']}/ai/chat", json={"question": "What are my best sellers?"}, headers=auth("user-a")
    )
    assert resp.status_code == 200, resp.text
    assert orla.ai.calls, "ORLA never called the AI gateway, so the context could not be checked"
    sent = orla.ai.all_text()
    assert "Zebra Unicorn Saddle" not in sent and "777.77" not in sent, "Business B data was sent to the AI"

    from app.models.ai_request import AIRequest

    with orla.session() as s:
        rows = s.query(AIRequest).all()
    assert rows and all(str(r.business_id) == a["id"] for r in rows)


def test_branch_group_scoped_to_member(orla):
    """AC-006: someone who is only a member of a branch cannot pull the parent
    shop's figures through an "all branches" view."""
    parent = orla.create_business("owner-p", "Parent Shop")
    resp = orla.client.post(
        f"/businesses/{parent['id']}/branches",
        json={"name": "Branch Shop", "template": "bicycle_shop", "timezone": "Europe/Dublin"},
        headers=auth("owner-p"),
    )
    assert resp.status_code in (200, 201), f"creating a branch failed: {resp.text}"
    branch = resp.json()
    orla.seed_subscription(branch["id"])

    orla.import_file("owner-p", parent["id"], "p.csv", csv_bytes([
        SALES_HEADER, ["2026-01-05", "Parent Only Item", "PO-1", "1", "500.00", "100.00"],
    ]))
    orla.import_file("owner-p", branch["id"], "br.csv", csv_bytes([
        SALES_HEADER, ["2026-01-05", "Branch Item", "BI-1", "1", "70.00", "10.00"],
    ]))
    orla.add_member(branch["id"], "staff-s", "staff")

    resp = orla.client.get(
        f"/businesses/{branch['id']}/analytics/financial-performance",
        params={"all_branches": "true", "start": "2026-01-01", "end": "2026-01-31"},
        headers=auth("staff-s"),
    )
    if resp.status_code in (403, 404):
        return
    assert resp.status_code == 200, resp.text
    from decimal import Decimal

    assert Decimal(resp.json()["revenue"]["current"]) == Decimal("70.00"), (
        "A branch-only member received the parent shop's revenue via all_branches"
    )
