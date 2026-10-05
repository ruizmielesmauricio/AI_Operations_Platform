"""Runs the Ask ORLA question bank against a real business and scores it.

  python -m app.ai.eval --mode offline --business-id <uuid>
  python -m app.ai.eval --mode live    --business-id <uuid> --max-calls 40

offline  Free, instant, no AI provider. The classifier is replaced by the
         bank's own expected routing and the "explain" step by a stub that
         only repeats figures from the data. It proves the plumbing for
         every question: data is fetched, lookups resolve, refusals
         refuse, the number check and the leak check hold.
live     The real AI provider. Works in batches (--max-calls) so it fits
         inside a free daily allowance; results are saved to a JSONL file
         and the next run carries on where this one stopped.

Not part of the app at runtime. Everything is read-only against the
business's data (it only adds rows to the AI usage log).
"""

import argparse
import json
import re
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import client, service
from app.ai.eval.question_bank import QUESTIONS, Q
from app.ai.eval.scoring import (
    FAIL_ERROR, FAIL_VERDICTS, INFRA, PASS, SKIPPED, Verdict, score,
)
from app.analytics import period as period_module
from app.models.ai_request import AIRequest
from app.models.base import SessionLocal
from app.models.business import Business
from app.models.inventory_movement import InventoryMovement
from app.models.membership import Membership
from app.models.product import Product
from app.models.production_event import ProductionEvent
from app.models.sale import Sale, SaleItem
from app.models.supplier import Supplier

_RESULTS_DIR = Path("eval_results")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_INFRA_STREAK_LIMIT = 3


# --- Fixtures: real names/dates from the business under test -----------------


def _first(db: Session, stmt) -> Any:
    return db.execute(stmt).scalars().first()


def resolve_fixtures(db: Session, business: Business, as_of: date) -> dict[str, str]:
    bid = business.id
    top_product = db.execute(
        select(Product.name, Product.sku)
        .join(SaleItem, SaleItem.product_id == Product.id)
        .where(Product.business_id == bid)
        .group_by(Product.id, Product.name, Product.sku)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(1)
    ).first()
    from app.models.product import ProductCategory  # local: avoids an import cycle on some layouts

    categories = list(db.execute(select(ProductCategory.name).where(ProductCategory.business_id == bid).order_by(ProductCategory.name)).scalars())
    fx = {
        "product": top_product[0] if top_product else "Sample Product",
        "sku": (top_product[1] if top_product else None) or "SKU-00001",
        "sku_nonexistent": "SKU-NOPE-99999",
        "category": categories[0] if categories else "Accessories",
        "category_b": categories[1] if len(categories) > 1 else "Components",
        "supplier": _first(db, select(Supplier.name).where(Supplier.business_id == bid).order_by(Supplier.name)) or "Supplier 01",
        "po_ref": _first(db, select(InventoryMovement.purchase_reference).where(
            InventoryMovement.business_id == bid, InventoryMovement.purchase_reference.is_not(None))) or "PO-0001",
        "repair_ref": _first(db, select(ProductionEvent.repair_reference).where(
            ProductionEvent.business_id == bid, ProductionEvent.repair_reference.is_not(None))) or "JOB-0001",
        "d_yesterday": (as_of - timedelta(days=1)).isoformat(),
        "d_sample": (as_of - timedelta(days=12)).isoformat(),
        "day_nice": (as_of - timedelta(days=12)).strftime("%-d %B"),
        "d_range_start": (as_of - timedelta(days=21)).isoformat(),
        "d_range_end": (as_of - timedelta(days=14)).isoformat(),
    }
    return fx


def fill(value: Any, fixtures: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: fixtures.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: fill(v, fixtures) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(fill(v, fixtures) for v in value)
    return value


def default_as_of(db: Session, business_id: uuid.UUID) -> date:
    last = db.execute(select(func.max(Sale.sold_at)).where(Sale.business_id == business_id)).scalar()
    return (last.date() + timedelta(days=1)) if last else datetime.now(timezone.utc).date()


# --- Offline stubs ------------------------------------------------------------


@dataclass
class _Current:
    parts: list[dict]
    raw: str | None = None  # the model's own explain text, kept for diagnosing failures


def _numbers_in(node: Any, limit: int = 2) -> list[str]:
    found: list[str] = []

    def walk(n: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(n, bool):
            return
        if isinstance(n, str) and re.fullmatch(r"-?\d+\.\d+", n):
            found.append(n)
        elif isinstance(n, dict):
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(node)
    return found


def make_offline_chat(current: _Current):
    """A stand-in for app.ai.client.chat_completion. Classify calls get the
    bank's expected routing; explain calls get a line that only repeats
    figures present in the data (so the number check has something real
    to verify)."""

    def fake(*, messages, response_format=None, max_tokens=500, temperature=0.2):
        if response_format is not None:
            payload = {"intents": [{"period": None, **p} for p in current.parts]}
            return {"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {}, "model": "offline-stub"}
        system = messages[0]["content"]
        marker = system.index("location breakdown.)\n")
        context, _ = json.JSONDecoder().raw_decode(system[system.index("{", marker):])
        part_keys = sorted(k for k in context if re.fullmatch(r"part_\d+", k))
        if part_keys:
            lines = []
            for key in part_keys:
                n = key.split("_")[1]
                nums = _numbers_in(context[key].get("data"))
                lines.append(f"⟦PART_{n}⟧")
                lines.append("Here is what your data shows: " + (", ".join(nums) if nums else "nothing to report for this period") + ".")
            text = "\n".join(lines)
        else:
            nums = _numbers_in(context)
            text = "Here is what your data shows: " + (", ".join(nums) if nums else "nothing to report for this period") + "."
        return {"choices": [{"message": {"content": text}}], "usage": {}, "model": "offline-stub"}

    return fake


# --- Known figures (so a wrong-number answer is caught, not just a made-up one)


def expected_figures_for(db: Session, business: Business, q: Q, as_of_dt: datetime) -> tuple[Decimal, ...]:
    """For the plain "what's my revenue / profit margin" questions, the
    figure the answer must state, taken straight from the same analytics
    the dashboard uses."""
    from app.application.financial_performance import get_financial_performance

    wanted = {"What's my revenue?": "revenue", "What's my profit margin?": "margin", "What is my gross margin this month?": None}
    kind = wanted.get(q.text)
    if kind is None:
        return ()
    summary = get_financial_performance(db, business_id=business.id)
    if kind == "revenue":
        return (Decimal(str(summary.revenue.current)),)
    gm = summary.gross_margin
    vals = [v for v in (gm.gross_margin_pct, getattr(gm, "net_gross_margin_pct", None)) if v is not None]
    return tuple(Decimal(str(v)) for v in vals)


# --- Results file ---------------------------------------------------------------


def load_results(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[rec["id"]] = rec
    return latest


def append_result(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


# --- One question ---------------------------------------------------------------


def _ai_calls_today(db: Session, business_id: uuid.UUID) -> int:
    return db.execute(select(func.count()).select_from(AIRequest).where(AIRequest.business_id == business_id)).scalar() or 0


def run_one(db: Session, *, q: Q, business: Business, user_id: str, fixtures: dict[str, str], as_of_dt: datetime,
            previous: dict | None, current: _Current, offline: bool = False) -> dict:
    text = fill(q.text, fixtures)
    filled = Q(**{**q.__dict__, "text": text, "parts": tuple(fill(p, fixtures) for p in q.parts),
                  "must_contain_any": q.must_contain_any, "must_not_contain": q.must_not_contain})
    current.parts = list(filled.parts)
    current.raw = None

    calls_before = _ai_calls_today(db, business.id)
    started = time.monotonic()
    try:
        result = service.answer_question(
            db, business_id=business.id, user_id=user_id, question=text, now=as_of_dt,
            previous_question=previous["question"] if previous else None,
            previous_answer=previous["answer"] if previous else None,
            previous_intent=(previous["intents"][0] if previous and previous.get("intents") else None),
            previous_intents=previous.get("intents") if previous else None,
        )
    except Exception as exc:  # the pipeline must never raise on any question
        db.rollback()
        return {"id": q.id, "category": q.category, "question": text, "verdict": FAIL_ERROR,
                "reasons": [f"{type(exc).__name__}: {exc}"[:300]], "answer": "", "intents": [], "ai_calls": 0, "seconds": 0}
    ai_calls = _ai_calls_today(db, business.id) - calls_before
    # Offline leaves no trace at all; live keeps the usage rows (they are
    # the real record of what the run cost).
    if offline:
        db.rollback()
    else:
        db.commit()
    figures = expected_figures_for(db, business, filled, as_of_dt) if (q.kind == "answer" and not offline) else ()
    intents = tuple(result.intents) if result.intents else (result.intent,)
    verdict = score(
        filled, actual_intents=intents, answer=result.answer, grounded=result.grounded,
        safe_fallbacks=(service._SAFE_FALLBACK,), ungrounded_fallback=service._UNGROUNDED_FALLBACK,
        ai_calls=ai_calls, expected_figures=figures,
    )
    notes = []
    if q.kind == "define" and ai_calls > 0:
        notes.append("definition went to the AI instead of the free glossary shortcut")
    return {"id": q.id, "category": q.category, "kind": q.kind, "question": text, "verdict": verdict.verdict,
            "notes": notes, "reasons": list(verdict.reasons), "answer": result.answer, "intents": list(intents),
            "expected": list(filled.intents), "grounded": result.grounded, "ai_calls": ai_calls,
            "raw_answer": current.raw if verdict.verdict != PASS else None,
            "seconds": round(time.monotonic() - started, 2)}


# --- Report ---------------------------------------------------------------------


def summarize(results: dict[str, dict], questions: list[Q]) -> str:
    by_cat: dict[str, Counter] = defaultdict(Counter)
    for q in questions:
        rec = results.get(q.id)
        by_cat[q.category][rec["verdict"] if rec else "NOT RUN"] += 1
    totals = Counter()
    for c in by_cat.values():
        totals.update(c)
    scored = sum(v for k, v in totals.items() if k in (PASS, *FAIL_VERDICTS))
    lines = ["| Category | Pass | Fail | Provider issue | Skipped | Not run |", "|---|---|---|---|---|---|"]
    for cat, c in sorted(by_cat.items()):
        lines.append(f"| {cat} | {c[PASS]} | {sum(c[v] for v in FAIL_VERDICTS)} | {c[INFRA]} | {c[SKIPPED]} | {c['NOT RUN']} |")
    lines.append(f"| **Total** | **{totals[PASS]}** | **{sum(totals[v] for v in FAIL_VERDICTS)}** | {totals[INFRA]} | {totals[SKIPPED]} | {totals['NOT RUN']} |")
    rate = f"{totals[PASS] / scored:.0%}" if scored else "n/a"
    out = [f"**Pass rate on questions that completed: {rate}** ({totals[PASS]} of {scored}).", "", *lines]
    defs = [r for q in questions if q.kind == "define" and (r := results.get(q.id)) and r["verdict"] == PASS]
    paid_defs = [r for r in defs if r.get("notes")]
    if defs:
        out += ["", f"Definitions answered free from the glossary: {len(defs) - len(paid_defs)} of {len(defs)}."]
        for r in paid_defs:
            out.append(f"- went to the AI (costs a call): \"{r['question']}\"")
    fails = [r for q in questions if (r := results.get(q.id)) and r["verdict"] in FAIL_VERDICTS]
    if fails:
        out += ["", "### Failures", "", "| Id | Verdict | Question | Why |", "|---|---|---|---|"]
        for r in fails:
            why = "; ".join(r["reasons"]).replace("|", "/")
            out.append(f"| {r['id']} | {r['verdict']} | {r['question'][:70].replace('|', '/')} | {why[:140]} |")
    return "\n".join(out)


# --- Main -----------------------------------------------------------------------


def select_questions(args) -> list[Q]:
    qs = list(QUESTIONS)
    if args.only:
        wanted = set(args.only.split(","))
        qs = [q for q in qs if q.id in wanted or q.id.split("-")[0] in wanted or q.category in wanted]
    return qs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.ai.eval")
    p.add_argument("--mode", choices=("offline", "live"), required=True)
    p.add_argument("--business-id", required=True)
    p.add_argument("--as-of", help="YYYY-MM-DD the questions are asked 'on' (default: the day after the last sale)")
    p.add_argument("--only", help="comma list of ids, id prefixes (FIN) or categories")
    p.add_argument("--max-calls", type=int, default=40, help="live: stop before exceeding this many AI calls this run")
    p.add_argument("--sleep", type=float, default=4.0, help="live: seconds between questions (free tier allows ~20/min)")
    p.add_argument("--redo-failed", action="store_true", help="re-run questions that failed or hit a provider issue")
    p.add_argument("--fresh", action="store_true", help="ignore saved results and start over")
    p.add_argument("--rescore", action="store_true", help="re-judge saved answers against the current bank (no AI calls)")
    p.add_argument("--results", help="results file (default eval_results/<mode>.jsonl)")
    p.add_argument("--report", help="also write the summary as markdown to this path")
    args = p.parse_args(argv)

    results_path = Path(args.results) if args.results else _RESULTS_DIR / f"{args.mode}.jsonl"
    if args.fresh and results_path.exists():
        results_path.unlink()
    results = load_results(results_path)
    questions = select_questions(args)
    by_id = {q.id: q for q in QUESTIONS}

    if args.rescore:
        for qid, rec in results.items():
            q = by_id.get(qid)
            if q is None or rec["verdict"] in (INFRA, SKIPPED, FAIL_ERROR) or not rec.get("intents"):
                continue
            v = score(q, actual_intents=tuple(rec["intents"]), answer=rec["answer"], grounded=rec.get("grounded", True),
                      safe_fallbacks=(service._SAFE_FALLBACK,), ungrounded_fallback=service._UNGROUNDED_FALLBACK,
                      ai_calls=rec.get("ai_calls", 0))
            if v.verdict != rec["verdict"] or list(v.reasons) != rec.get("reasons"):
                rec = {**rec, "verdict": v.verdict, "reasons": list(v.reasons)}
                results[qid] = rec
                append_result(results_path, rec)
        summary = summarize(results, list(QUESTIONS))
        print(summary)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(summary + "\n")
        return 0

    with SessionLocal() as db:
        business = db.get(Business, uuid.UUID(args.business_id))
        if business is None:
            print("No such business", file=sys.stderr)
            return 2
        owner = db.execute(select(Membership.user_id).where(Membership.business_id == business.id, Membership.role == "owner")).scalars().first()
        if owner is None:
            print("That business has no owner membership", file=sys.stderr)
            return 2
        as_of = date.fromisoformat(args.as_of) if args.as_of else default_as_of(db, business.id)
        as_of_dt = datetime.combine(as_of, dtime(9, 0), tzinfo=timezone.utc)
        fixtures = resolve_fixtures(db, business, as_of)
        has_workshop = business.template == "bicycle_shop"

        # "Today" for the data windows must be the as-of date, otherwise a
        # business whose data ends last month would answer every
        # "recent" question with an empty period.
        period_module.resolve_period.__kwdefaults__["now"] = as_of_dt

        current = _Current(parts=[])
        if args.mode == "offline":
            client.chat_completion = make_offline_chat(current)
        # The app's per-business daily cap looks back from "now" — and the
        # questions are asked "as of" an earlier date, so it would count every
        # row ever logged and refuse. The run has its own budget (--max-calls)
        # and the provider's own limits still apply, so lift the app cap here.
        from app.settings.config import get_settings
        get_settings().ai_daily_request_limit_per_business = 10**9
        offline = args.mode == "offline"

        original_generate = service._generate_answer

        def _recording_generate(*a, **kw):
            text = original_generate(*a, **kw)
            current.raw = text
            return text

        service._generate_answer = _recording_generate

        print(f"{args.mode} run · {business.name} · as of {as_of} · {len(questions)} questions · results → {results_path}")
        calls_used = 0
        infra_streak = 0
        ran = 0
        for q in questions:
            prior = results.get(q.id)
            if prior and not args.fresh:
                retry = prior["verdict"] in FAIL_VERDICTS + (INFRA,)
                if not (args.redo_failed and retry):
                    if prior["verdict"] != INFRA or not args.redo_failed:
                        if prior["verdict"] != INFRA:
                            continue
            if q.needs_workshop and not has_workshop:
                rec = {"id": q.id, "category": q.category, "kind": q.kind, "question": q.text, "verdict": SKIPPED,
                       "reasons": ["business has no workshop"], "answer": "", "intents": [], "ai_calls": 0, "seconds": 0}
                results[q.id] = rec
                append_result(results_path, rec)
                continue
            if args.mode == "live" and calls_used >= args.max_calls:
                print(f"Stopping: reached --max-calls {args.max_calls}. Run again to continue.")
                break

            previous = None
            if q.follow_up_to:
                prev_rec = results.get(q.follow_up_to)
                if prev_rec is None or prev_rec["verdict"] in (INFRA, FAIL_ERROR) or not prev_rec.get("answer"):
                    prev_q = by_id[q.follow_up_to]
                    prev_rec = run_one(db, q=prev_q, business=business, user_id=owner, fixtures=fixtures,
                                       as_of_dt=as_of_dt, previous=None, current=current, offline=offline)
                    results[prev_q.id] = prev_rec
                    append_result(results_path, prev_rec)
                    calls_used += prev_rec["ai_calls"]
                if prev_rec["verdict"] == INFRA:
                    infra_streak += 1
                    continue
                previous = prev_rec

            rec = run_one(db, q=q, business=business, user_id=owner, fixtures=fixtures, as_of_dt=as_of_dt,
                          previous=previous, current=current, offline=offline)
            results[q.id] = rec
            append_result(results_path, rec)
            calls_used += rec["ai_calls"]
            ran += 1
            flag = "ok " if rec["verdict"] == PASS else rec["verdict"]
            print(f"  {rec['id']:7} {flag:14} {rec['question'][:62]}")
            if rec["verdict"] == INFRA:
                infra_streak += 1
                if infra_streak >= _INFRA_STREAK_LIMIT:
                    print("Stopping: the AI provider failed 3 times in a row (probably the free daily limit). "
                          "Progress is saved — run again later.")
                    break
            else:
                infra_streak = 0
            if args.mode == "live":
                time.sleep(args.sleep)

        summary = summarize(results, list(QUESTIONS))
        print("\n" + summary)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(summary + "\n")
        print(f"\nThis run: {ran} questions, {calls_used} AI calls.")
    return 0
