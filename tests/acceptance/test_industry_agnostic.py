"""Industry-agnostic core — AC-015..AC-018 (criteria §3)."""

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from conftest import BACKEND, REPO_ROOT, SALES_HEADER, auth, csv_bytes, recent_weekly_run

APP = BACKEND / "app"
_VERTICAL_WORDS = re.compile(r"\b(bikes?|bicycles?|cycling|mechanics?|e-?bikes?)\b", re.I)
_SCHEMA_VERTICAL_WORDS = re.compile(r"(repair|bike|bicycle|mechanic|prescription|recipe|warranty|workshop)", re.I)
_FRONTEND_TEMPLATE_DIR = REPO_ROOT / "frontend" / "lib" / "templates"


def _docstring_nodes(tree) -> set[int]:
    """Docstrings and bare string statements are documentation, not logic."""
    return {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


def _python_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    docstrings = _docstring_nodes(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if _VERTICAL_WORDS.search(node.value) or node.value in {"bicycle_shop", "coffee_shop", "pharmacy"}:
                out.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} literal {node.value[:60]!r}")
        elif isinstance(node, ast.Name) and _VERTICAL_WORDS.search(node.id.replace("_", " ")):
            out.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} identifier {node.id}")
    return out


def _strip_ts_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(^|[^:])//.*$", r"\1", src, flags=re.M)


def test_no_vertical_specific_logic_in_core():
    """AC-015: no bike-specific literals/identifiers or hard-coded template-name
    branches in core code. Vertical behaviour lives in backend/app/templates/
    and frontend/lib/templates/ (configuration), nowhere else. Comments and
    docstrings are allowed to mention examples."""
    problems = []
    for path in APP.rglob("*.py"):
        if "__pycache__" in path.parts or APP / "templates" in path.parents:
            continue
        problems += _python_violations(path)
    for sub in ("app", "components", "lib", "types"):
        for path in (REPO_ROOT / "frontend" / sub).rglob("*.ts*"):
            if _FRONTEND_TEMPLATE_DIR in path.parents:
                continue
            code = _strip_ts_comments(path.read_text())
            for lineno, line in enumerate(code.splitlines(), 1):
                strings = re.findall(r"([\"'`])(.*?)\1", line)
                if any(_VERTICAL_WORDS.search(s) or s in ("bicycle_shop", "coffee_shop") for _, s in strings):
                    problems.append(f"{path.relative_to(REPO_ROOT)}:{lineno} {line.strip()[:80]}")
                elif re.search(r"\b(bike|bicycle)", line, re.I) and not strings:
                    problems.append(f"{path.relative_to(REPO_ROOT)}:{lineno} {line.strip()[:80]}")
    assert not problems, f"{len(problems)} vertical-specific references in core code:\n" + "\n".join(problems[:80])


def test_core_schema_is_industry_neutral():
    """AC-016: no core table/column named for one industry; vertical tables
    are allowed only when a template declares them in its EXTENSION_TABLES.
    Business has no default template — it is chosen at signup."""
    import importlib
    import pkgutil

    import app.templates as templates_pkg
    from app.models import Base
    from app.models.business import Business
    from app.schemas.business import BusinessCreate

    declared = set()
    for mod in pkgutil.iter_modules(templates_pkg.__path__):
        m = importlib.import_module(f"app.templates.{mod.name}")
        declared |= set(getattr(m, "EXTENSION_TABLES", ()))

    problems = []
    for table in Base.metadata.sorted_tables:
        if table.name in declared:
            continue
        if _SCHEMA_VERTICAL_WORDS.search(table.name):
            problems.append(f"table {table.name}")
        for col in table.c:
            if _SCHEMA_VERTICAL_WORDS.search(col.name):
                problems.append(f"column {table.name}.{col.name}")
    tcol = Business.__table__.c.template
    if tcol.default is not None or tcol.server_default is not None:
        problems.append("businesses.template has a default (a vertical is assumed)")
    if not BusinessCreate.model_fields["template"].is_required():
        problems.append("BusinessCreate.template is optional (a vertical is assumed)")
    assert not problems, "\n".join(problems)


def _all_json(orla, user, biz_id) -> str:
    h = auth(user)
    texts = []
    for path in ("financial-performance", "retail-operations", "category-breakdown", "findings", "forecast"):
        r = orla.client.get(f"/businesses/{biz_id}/analytics/{path}",
                            params={},
                            headers=h)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        texts.append(r.text)
    for path in ("", "/notifications", "/alerts", "/reports", "/search?q=flat"):
        r = orla.client.get(f"/businesses/{biz_id}{path}", headers=h)
        assert r.status_code == 200, f"{path}: {r.status_code}"
        texts.append(r.text)
    return "\n".join(texts)


def _coffee_shop(orla):
    _, week = recent_weekly_run()
    biz = orla.create_business("cafe-owner", "Bean There", template="coffee_shop")
    orla.import_file("cafe-owner", biz["id"], "till.csv", csv_bytes([
        SALES_HEADER,
        [week[0].isoformat(), "Flat White", "FW", "30", "3.80", "0.90"],
        [week[1].isoformat(), "Almond Croissant", "AC", "12", "3.50", "1.10"],
        [week[2].isoformat(), "Flat White", "FW", "25", "3.80", "0.90"],
    ]))
    return biz


def test_non_bike_business_end_to_end(orla):
    """AC-017: a coffee shop goes signup -> upload -> dashboard -> weekly
    report, and never sees bicycle vocabulary."""
    bad = orla.client.post("/businesses", json={"name": "X", "template": "not_a_real_template"},
                           headers=auth("someone"))
    assert bad.status_code == 422, "unknown business types must be rejected, so coffee_shop must be a real template"

    biz = _coffee_shop(orla)
    from app.scheduler.tick import run_tick

    with orla.session() as s:
        run_tick(s, now=recent_weekly_run()[0])
    reports = orla.client.get(f"/businesses/{biz['id']}/reports", headers=auth("cafe-owner")).json()
    weekly = [r for r in reports if r["report_type"] == "weekly"]
    assert weekly, "no weekly report for the coffee shop"
    detail = orla.client.get(f"/businesses/{biz['id']}/reports/{weekly[0]['id']}", headers=auth("cafe-owner"))
    assert detail.status_code == 200
    blob = _all_json(orla, "cafe-owner", biz["id"]) + detail.text
    hits = sorted(set(m.group(0) for m in _VERTICAL_WORDS.finditer(blob)))
    assert not hits, f"bicycle vocabulary shown to a coffee shop: {hits}"


def _keys(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield prefix + k
            yield from _keys(v, prefix + k + ".")
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v, prefix)


def test_inapplicable_sections_omitted(orla):
    """AC-018: sections a template doesn't use are absent, not null/placeholder;
    a template that uses them gets them."""
    from app.scheduler.tick import run_tick

    cafe = _coffee_shop(orla)
    run_at, week = recent_weekly_run()
    bike = orla.create_business("bike-owner", "Spokes", template="bicycle_shop")
    orla.import_file("bike-owner", bike["id"], "s.csv", csv_bytes([
        SALES_HEADER, [week[0].isoformat(), "Inner Tube", "IT", "3", "8.00", "3.00"],
    ]))
    orla.import_file("bike-owner", bike["id"], "jobs.csv", csv_bytes([
        ["Date", "Description", "Price", "Labour Cost"],
        [week[1].isoformat(), "Full service", "90.00", "40.00"],
    ]), entity_type="repairs")
    with orla.session() as s:
        run_tick(s, now=run_at)

    def weekly_payload(user, biz):
        reports = orla.client.get(f"/businesses/{biz['id']}/reports", headers=auth(user)).json()
        rid = next(r["id"] for r in reports if r["report_type"] == "weekly")
        return orla.client.get(f"/businesses/{biz['id']}/reports/{rid}", headers=auth(user)).json()["payload"]

    cafe_keys = [k for k in _keys(weekly_payload("cafe-owner", cafe)) if re.search(r"workshop|repair", k, re.I)]
    assert not cafe_keys, f"coffee-shop report carries inapplicable sections: {cafe_keys}"
    bike_payload = weekly_payload("bike-owner", bike)
    assert bike_payload.get("workshop_performance"), "bike-shop report is missing its workshop section"
