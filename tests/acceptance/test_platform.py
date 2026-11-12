"""Non-functional and platform safety — AC-074, 075, 078..082 (criteria §9)."""

import ast
import re
import subprocess
import time
from datetime import date, timedelta

import pytest

from conftest import BACKEND, REPO_ROOT, SALES_HEADER, auth, csv_bytes

# "Typical business" (decided 12/11/2026): one year of history, 5,000 sales,
# 500 products, 2 locations.
TYPICAL_SALES, TYPICAL_PRODUCTS, TYPICAL_DAYS = 5000, 500, 365


def _typical_rows(n_rows, product_offset=0):
    today = date.today()
    rows = [SALES_HEADER]
    for i in range(n_rows):
        p = (i * 7 + product_offset) % TYPICAL_PRODUCTS
        rows.append([(today - timedelta(days=1 + i % TYPICAL_DAYS)).isoformat(), f"Product {p:03d}", f"SKU-{p:03d}",
                     str(1 + i % 4), f"{5 + p % 40}.{i % 100:02d}", f"{2 + p % 20}.50"])
    return rows


def test_dashboard_under_2s(orla):
    """AC-074: every dashboard call answers in under 2 seconds for a typical
    business (both locations, all-branches view included)."""
    parent = orla.create_business("perf-owner", "Typical Main")
    branch = orla.client.post(f"/businesses/{parent['id']}/branches",
                              json={"name": "Typical Branch", "template": "bicycle_shop",
                                    "timezone": "Europe/Dublin"}, headers=auth("perf-owner"))
    assert branch.status_code in (200, 201), branch.text
    branch = branch.json()
    orla.seed_subscription(branch["id"])
    orla.import_file("perf-owner", parent["id"], "main.csv", csv_bytes(_typical_rows(3000)))
    orla.import_file("perf-owner", branch["id"], "branch.csv", csv_bytes(_typical_rows(2000, 3)))

    h = auth("perf-owner")
    year = {"start": (date.today() - timedelta(days=365)).isoformat(), "end": date.today().isoformat()}
    calls = []
    for all_branches in ("false", "true"):
        for path in ("financial-performance", "retail-operations", "category-breakdown", "findings", "forecast"):
            params = {"all_branches": all_branches, **({} if path == "forecast" else year)}
            calls.append((f"/businesses/{parent['id']}/analytics/{path}", params))
    calls += [(f"/businesses/{parent['id']}/alerts", {}), (f"/businesses/{parent['id']}/notifications", {}),
              (f"/businesses/{parent['id']}/transactions/sales", {"limit": 25})]
    slow = []
    for url, params in calls:
        t0 = time.perf_counter()
        r = orla.client.get(url, params=params, headers=h)
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, f"{url}: {r.status_code}"
        if elapsed >= 2.0:
            slow.append(f"{url} {params} took {elapsed:.2f}s")
    assert not slow, "\n".join(slow)


def test_10k_row_import_under_60s(orla):
    """AC-075: a 10,000-row export imports, end to end, in under 60 seconds."""
    biz = orla.create_business("bulk-owner")
    content = csv_bytes(_typical_rows(10_000))
    t0 = time.perf_counter()
    result = orla.import_file("bulk-owner", biz["id"], "big.csv", content)
    elapsed = time.perf_counter() - t0
    assert result["rows_imported"] == 10_000
    assert elapsed < 60, f"10k-row import took {elapsed:.1f}s"


def test_refuses_production_database(monkeypatch):
    """AC-078. Contract: app.settings.safety.assert_safe_database_target(
    database_url, environment, production_database_host) raises
    app.settings.safety.UnsafeDatabaseTarget whenever a non-production
    environment points at the production database, at any Supabase host,
    or at any remote host while the production host is not configured. It
    must run at API, scheduler and migration startup."""
    from app.settings import safety

    ok = safety.assert_safe_database_target
    unsafe = safety.UnsafeDatabaseTarget
    prod_host = "ep-prod-123456.eu-central-1.aws.neon.tech"
    dev_url = "postgresql+psycopg://u:p@ep-dev-branch-777.eu-central-1.aws.neon.tech/orla"
    prod_url = f"postgresql+psycopg://u:p@{prod_host}/orla"

    ok("sqlite:///test.db", "test", prod_host)
    ok("postgresql+psycopg://aiops:x@localhost:5432/aiops_dev", "local", prod_host)
    ok(dev_url, "local", prod_host)
    ok(prod_url, "production", prod_host)
    for url, env, host in [
        (prod_url, "local", prod_host),
        (prod_url, "test", prod_host),
        ("postgresql://u:p@db.abcdefgh.supabase.co:5432/postgres", "local", prod_host),
        (dev_url, "local", ""),
    ]:
        with pytest.raises(unsafe):
            ok(url, env, host)

    for path in (BACKEND / "app" / "main.py", BACKEND / "app" / "scheduler" / "__main__.py",
                 BACKEND / "migrations" / "env.py"):
        assert "assert_safe_database_target" in path.read_text(), f"{path.name} does not run the database guard"


_SECRET_PATTERNS = [
    (r"sk_live_[0-9A-Za-z]{10,}", "Stripe live secret key"),
    (r"rk_(live|test)_[0-9A-Za-z]{10,}", "Stripe restricted key"),
    (r"sk_test_[0-9A-Za-z]{20,}", "Stripe test secret key"),
    (r"whsec_[0-9A-Za-z]{20,}", "Stripe webhook secret"),
    (r"sk-or-v1-[0-9a-f]{20,}", "OpenRouter key"),
    (r"\bre_[0-9A-Za-z]{8,}_[0-9A-Za-z]{8,}", "Resend key"),
    (r"sb_secret_[0-9A-Za-z_-]{10,}", "Supabase secret key"),
    (r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]*c2VydmljZV9yb2xl[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+", "Supabase service-role JWT"),
    (r"postgres(ql)?(\+\w+)?://[^:\s/]+:(?!aiops_dev_password@|password@|postgres@|u@|p@|x@|\$\{)[^@\s]{6,}@(?!localhost|db[:/]|127\.0\.0\.1)",
     "database URL with a real password"),
]
_SECRET_ENV_KEYS = re.compile(r"^(\w*(SECRET|API_KEY|ACCESS_KEY|PASSWORD|TOKEN)\w*)=(.+)$")
_ALLOWED_ENV_VALUES = {"aiops_dev_password"}


def test_no_committed_secrets():
    """AC-079: nothing secret is committed — no keys, no real connection
    passwords, and every secret-looking key in .env.example files is blank."""
    files = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.split()
    problems = []
    for rel in files:
        path = REPO_ROOT / rel
        if rel.startswith("tests/acceptance/") or path.suffix in {".png", ".xlsx", ".xls", ".pdf", ".ico", ".lock"} \
                or not path.is_file():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for pattern, label in _SECRET_PATTERNS:
            if re.search(pattern, text):
                problems.append(f"{rel}: {label}")
        if path.name.endswith(".env.example") or path.name == ".env.example":
            for line in text.splitlines():
                m = _SECRET_ENV_KEYS.match(line.strip())
                if m and m.group(3).strip() and m.group(3).strip() not in _ALLOWED_ENV_VALUES:
                    problems.append(f"{rel}: {m.group(1)} has a value")
    assert not problems, "\n".join(problems)


def test_utc_storage_and_business_timezone(orla):
    """AC-080: timestamps are timezone-aware (stored UTC); every business has
    a timezone setting used for local-time logic."""
    from sqlalchemy import DateTime

    from app.models import Base
    from app.models.business import Business

    naive = [f"{t.name}.{c.name}" for t in Base.metadata.sorted_tables for c in t.c
             if isinstance(c.type, DateTime) and not c.type.timezone]
    assert not naive, f"naive timestamp columns: {naive}"
    tz = Business.__table__.c.timezone
    assert not tz.nullable
    biz = orla.create_business("tz-owner", timezone_name="America/New_York")
    assert orla.client.get(f"/businesses/{biz['id']}", headers=auth("tz-owner")).json()["timezone"] == "America/New_York"
    bad = orla.client.post("/businesses", json={"name": "X", "template": "bicycle_shop", "timezone": "Mars/Olympus"},
                           headers=auth("tz-other"))
    assert bad.status_code == 422, "an invalid timezone was accepted"


def test_errors_have_machine_codes(orla):
    """AC-081: error responses carry a machine-readable `code`."""
    biz = orla.create_business("err-owner")
    other = orla.create_business("err-other")
    import uuid

    cases = {
        "401": orla.client.get("/businesses"),
        "403": orla.client.get(f"/businesses/{other['id']}", headers=auth("err-owner")),
        "404": orla.client.post(f"/businesses/{biz['id']}/uploads/{uuid.uuid4()}/import", headers=auth("err-owner")),
        "422": orla.client.post("/businesses", json={}, headers=auth("err-new")),
    }
    missing = []
    for label, r in cases.items():
        assert str(r.status_code) == label, f"expected {label}, got {r.status_code}"
        code = r.json().get("code")
        if not (isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]+", code)):
            missing.append(f"{label}: {r.text[:120]}")
    assert not missing, "errors without a machine-readable code:\n" + "\n".join(missing)


def test_thin_route_handlers():
    """AC-082: route handlers don't run queries themselves; data access lives
    in repositories/application code. (The DB health probe is exempt.)"""
    offenders = []
    for path in (BACKEND / "app" / "api").glob("*.py"):
        if path.name in {"deps.py", "health.py", "__init__.py"}:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                    node.func.attr in {"query", "execute", "scalars", "scalar"}:
                offenders.append(f"{path.name}:{node.lineno} .{node.func.attr}(...)")
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy" and \
                    any(a.name in {"select", "update", "delete", "insert", "text"} for a in node.names):
                offenders.append(f"{path.name}:{node.lineno} imports sqlalchemy query builders")
    assert not offenders, "\n".join(offenders)
