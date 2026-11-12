"""AI explains only (Business Logic First) — AC-007..AC-014 (criteria §2)."""

import ast
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import BACKEND, REPO_ROOT, SALES_HEADER, auth, csv_bytes

APP = BACKEND / "app"
_PROVIDER_MODULES = ("openai", "anthropic", "openrouter", "google.generativeai", "google.genai",
                     "mistralai", "cohere", "litellm", "groq", "together")
_PROVIDER_HOSTS = re.compile(r"(openrouter\.ai|api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com)")


def _py_files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _module_name(path: Path) -> str:
    rel = path.relative_to(BACKEND).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    pkg = _module_name(path).rsplit(".", 1)[0] if path.name != "__init__.py" else _module_name(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")[: len(pkg.split(".")) - node.level + 1]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            found.add(mod)
            for a in node.names:
                found.add(f"{mod}.{a.name}")
    return found


def _is_ai(path: Path) -> bool:
    return APP / "ai" in path.parents


def _seed_sales(orla, user="owner-1"):
    biz = orla.create_business(user, "Grounded Shop")
    orla.import_file(user, biz["id"], "s.csv", csv_bytes([
        SALES_HEADER,
        ["2026-01-02", "Chain Lube", "CL-1", "4", "12.50", "5.00"],
        ["2026-01-03", "Bar Tape", "BT-1", "2", "20.00", "8.00"],
    ]))
    return biz


def test_no_provider_sdk_outside_ai_package():
    """AC-007: no AI provider/router SDK import, and no provider endpoint URL,
    outside backend/app/ai/. (app/settings/ holds configuration only and may
    name the configured base URL.)"""
    offenders = []
    for path in _py_files(APP):
        if _is_ai(path):
            continue
        for mod in _imports(path):
            if any(mod == p or mod.startswith(p + ".") for p in _PROVIDER_MODULES):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {mod}")
        if APP / "settings" not in path.parents and _PROVIDER_HOSTS.search(path.read_text()):
            offenders.append(f"{path.relative_to(REPO_ROOT)} references an AI provider host")
    for path in (REPO_ROOT / "frontend").rglob("*"):
        if path.suffix in {".ts", ".tsx", ".js", ".mjs"} and "node_modules" not in path.parts and ".next" not in path.parts:
            if _PROVIDER_HOSTS.search(path.read_text(errors="ignore")):
                offenders.append(f"{path.relative_to(REPO_ROOT)} calls an AI provider directly")
    assert not offenders, "\n".join(offenders)


def test_calculation_paths_do_not_import_ai():
    """AC-008: calculation and data-transformation code never reaches app.ai,
    directly or transitively. The importer may use only app.ai.column_mapping
    (the one-off mapping *suggestion*, ED-009)."""
    graph: dict[str, set[str]] = {}
    files = {_module_name(p): p for p in _py_files(APP)}
    for name, path in files.items():
        graph[name] = {m for m in _imports(path) if m.startswith("app.")}

    def reaches_ai(start: str, allow: tuple[str, ...]) -> list[str]:
        seen, stack = set(), [(start, [start])]
        while stack:
            mod, trail = stack.pop()
            for dep in graph.get(mod, ()):
                target = next((m for m in (dep, dep.rsplit(".", 1)[0]) if m in graph), None)
                if dep.startswith("app.ai") or (target or "").startswith("app.ai"):
                    if not any(dep.startswith(a) or (target or "").startswith(a) for a in allow):
                        return trail + [dep]
                    continue
                if target and target not in seen:
                    seen.add(target)
                    stack.append((target, trail + [target]))
        return []

    roots = [m for m in graph if m.startswith(("app.analytics", "app.forecasting", "app.scheduler"))]
    roots += ["app.application.report", "app.application.alerts", "app.application.forecast"]
    problems = [" -> ".join(t) for r in roots if r in graph for t in [reaches_ai(r, ())] if t]
    import_roots = [m for m in graph if m.startswith("app.imports")]
    problems += [" -> ".join(t) for r in import_roots for t in [reaches_ai(r, ("app.ai.column_mapping",))] if t]
    assert not problems, "Calculation paths that reach the AI layer:\n" + "\n".join(problems)


def test_unsupported_number_is_blocked(orla):
    """AC-009: a figure the model invents never reaches the user."""
    biz = _seed_sales(orla)
    orla.ai.explain = "Revenue hit an incredible €9,876,543.21 and margin was 87.3%."
    resp = orla.client.post(
        f"/businesses/{biz['id']}/ai/chat", json={"question": "How is revenue doing?"}, headers=auth("owner-1")
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "9,876,543.21" not in body["answer"] and "9876543.21" not in body["answer"]
    assert "87.3" not in body["answer"]
    assert body["grounded"] is False


def test_every_answer_traces_to_approved_source(orla):
    """AC-010 (PR-5.6, ADR-020). Contract: every chat response carries
    `source = {"kind": "query_function" | "help_article" | "none", "id": str|None}`.
    query_function ids must be keys of app.ai.registry.APPROVED_QUERY_FUNCTIONS;
    help_article ids keys of app.ai.registry.HELP_ARTICLES. A question with no
    approved source gets kind "none" and an answer with no figures."""
    from app.ai import registry  # noqa: F401  (must exist)

    biz = _seed_sales(orla)
    h = auth("owner-1")

    orla.ai.classify = {"intent": "financial_performance", "period": "default_recent", "metric": None}
    orla.ai.explain = "Revenue is shown on your dashboard."
    r1 = orla.client.post(f"/businesses/{biz['id']}/ai/chat", json={"question": "How's revenue?"}, headers=h).json()
    assert r1["source"]["kind"] == "query_function"
    assert r1["source"]["id"] in registry.APPROVED_QUERY_FUNCTIONS

    r2 = orla.client.post(
        f"/businesses/{biz['id']}/ai/chat", json={"question": "How do I upload my sales file?"}, headers=h
    ).json()
    assert r2["source"]["kind"] in ("help_article", "none")
    if r2["source"]["kind"] == "help_article":
        assert r2["source"]["id"] in registry.HELP_ARTICLES

    orla.ai.classify = {"intent": "out_of_scope", "period": None, "metric": None}
    r3 = orla.client.post(
        f"/businesses/{biz['id']}/ai/chat", json={"question": "Who will win the next election?"}, headers=h
    ).json()
    assert r3["source"]["kind"] == "none"
    assert not re.search(r"\d", r3["answer"]), "an unsourced answer must not contain figures"


def test_ai_outage_degrades_gracefully(orla):
    """AC-011: provider down -> metrics still served, chat says so plainly."""
    from app.ai.exceptions import AIProviderError

    biz = _seed_sales(orla)
    orla.ai.raise_error = AIProviderError("simulated outage")
    h = auth("owner-1")
    for path in ("financial-performance", "retail-operations", "findings", "forecast"):
        r = orla.client.get(f"/businesses/{biz['id']}/analytics/{path}", headers=h)
        assert r.status_code == 200, f"{path} failed during an AI outage: {r.status_code}"
    chat = orla.client.post(f"/businesses/{biz['id']}/ai/chat", json={"question": "How's revenue?"}, headers=h)
    assert chat.status_code == 200
    answer = chat.json()["answer"]
    assert answer and "Traceback" not in answer and "AIProviderError" not in answer
    assert re.search(r"unavailable|try again|can't|cannot|not available", answer, re.I)


def test_per_tenant_ai_limit_and_logging(orla, monkeypatch):
    """AC-012: 300 questions per business per calendar month (setting
    `ai_monthly_question_limit_per_business`), enforced server-side with a
    machine-readable outcome; every AI call logged."""
    from app.ai.service import answer_question
    from app.models.ai_request import AIRequest
    from app.settings.config import get_settings

    settings = get_settings()
    assert getattr(settings, "ai_monthly_question_limit_per_business", None) == 300
    monkeypatch.setattr(settings, "ai_monthly_question_limit_per_business", 3)

    biz = _seed_sales(orla)
    import uuid

    bid = uuid.UUID(biz["id"])
    with orla.session() as s:
        for day in (2, 3, 4):
            r = answer_question(s, business_id=bid, user_id="owner-1", question="How's revenue?",
                                now=datetime(2026, 3, day, 10, tzinfo=timezone.utc))
            assert r.intent != "usage_limit_reached", f"blocked too early on day {day}"
        blocked = answer_question(s, business_id=bid, user_id="owner-1", question="How's revenue?",
                                  now=datetime(2026, 3, 5, 10, tzinfo=timezone.utc))
        assert blocked.intent == "usage_limit_reached"
        next_month = answer_question(s, business_id=bid, user_id="owner-1", question="How's revenue?",
                                     now=datetime(2026, 4, 1, 10, tzinfo=timezone.utc))
        assert next_month.intent != "usage_limit_reached", "limit must reset each calendar month"

        rows = s.query(AIRequest).all()
        assert rows
        for row in rows:
            assert row.provider and row.model and row.lane and row.user_id == "owner-1"
            assert row.business_id == bid and row.cost_eur is not None and row.success is not None
            assert row.tokens_in is not None and row.tokens_out is not None


def test_report_generation_never_calls_ai(orla, monkeypatch):
    """AC-013: scheduled reports are produced with zero AI gateway calls."""
    from app.scheduler.tick import run_tick

    biz = _seed_sales(orla)
    orla.ai.raise_error = AssertionError("report generation called the AI gateway")
    with orla.session() as s:
        run_tick(s, now=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc))
        from app.models.report import Report

        reports = s.query(Report).all()
    assert any(r.status == "completed" for r in reports)
    assert orla.ai.calls == []


def test_mapping_suggestion_used_once(orla):
    """AC-014: the second upload from the same source reuses the saved mapping
    with no AI call and no mapping input."""
    biz = orla.create_business("owner-1")
    header = ["Txn Dt", "Item Desc", "Units", "Each"]
    first = orla.import_file("owner-1", biz["id"], "pos1.csv", csv_bytes([
        header, ["2026-01-02", "Widget", "1", "5.00"],
    ]), mapping={"sale_date": "Txn Dt", "product_name": "Item Desc", "quantity": "Units", "unit_price": "Each"})
    assert first["rows_imported"] == 1
    calls_before = len(orla.ai.calls)
    upload_id = orla.start_upload("owner-1", biz["id"], "pos2.csv", csv_bytes([
        header, ["2026-01-03", "Gadget", "2", "7.00"],
    ]))
    detected = orla.detect("owner-1", biz["id"], upload_id)
    assert detected["status"] == "reused"
    assert detected["suggested_mapping"]["sale_date"] == "Txn Dt"
    orla.confirm("owner-1", biz["id"], upload_id, detected["suggested_mapping"])
    assert orla.run_import("owner-1", biz["id"], upload_id)["rows_imported"] == 1
    assert len(orla.ai.calls) == calls_before, "the AI was consulted again for an already-mapped source"
