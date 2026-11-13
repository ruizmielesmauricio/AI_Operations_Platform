"""Ask ORLA accuracy eval runner (ORLA-91).

Runs every case in tests/ai_eval/cases.json through the real
app.ai.service.answer_question pipeline — real classify/explain calls to the
configured OpenRouter model, real data — and scores each answer against
facts computed deterministically from the database (tests/ai_eval/facts.py).
Writes a dated Markdown report (committed) and a JSON detail file
(git-ignored) to tests/ai_eval/reports/.

Run inside the backend container, from backend/:

    python scripts/eval_ask_orla.py                    # full run
    python scripts/eval_ask_orla.py --dry-run          # resolve facts only, no AI calls
    python scripts/eval_ask_orla.py --only fin-01,fu-03
    python scripts/eval_ask_orla.py --failed-from tests/ai_eval/reports/<run>.json

What it patches, for observation only (never what the pipeline decides):
- app.ai.client.chat_completion is wrapped to record each call (kind, raw
  output, tokens, latency) and to pace calls under the free tier's
  per-minute limit.
- AIRequestRepository.create / count_today_for_business are replaced so an
  eval run neither consumes the business's real daily question cap nor
  writes eval traffic into its usage log (pass --log-usage to keep both).
- service._build_part, support_lane.retrieve and service.validate_grounded
  are wrapped to capture what the deterministic layers supplied, so the
  scorer can independently check the *final* answer for unsupported numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.ai import client, service, support_lane  # noqa: E402
from app.ai.glossary import METRIC_DEFINITIONS  # noqa: E402
from app.models.base import SessionLocal  # noqa: E402
from app.models.business import Business  # noqa: E402
from app.models.membership import Membership  # noqa: E402
from app.repositories.ai_request import AIRequestRepository  # noqa: E402
from app.settings.config import get_settings  # noqa: E402
from tests.ai_eval.facts import FactEnv, resolve_fact  # noqa: E402
from tests.ai_eval.scoring import score_turn  # noqa: E402

EVAL_DIR = BACKEND_ROOT / "tests" / "ai_eval"
CASES_PATH = EVAL_DIR / "cases.json"
REPORTS_DIR = EVAL_DIR / "reports"


class Recorder:
    """Everything observed during one turn."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.calls: list[dict] = []
        self.parts: list[dict] = []
        self.passages: list[str] = []
        self.guardrail: list[dict] = []


REC = Recorder()
_LAST_CALL_AT = [0.0]


def _install_hooks(*, pace_seconds: float, log_usage: bool) -> None:
    real_chat = client.chat_completion

    def chat_completion(**kwargs: Any) -> dict:
        wait = _LAST_CALL_AT[0] + pace_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        system = (kwargs.get("messages") or [{}])[0].get("content", "")
        kind = "classify" if system.startswith("You are an intent classifier") else (
            "support" if "HELP PASSAGES" in system else "explain"
        )
        started = time.monotonic()
        try:
            response = real_chat(**kwargs)
        except Exception as exc:
            REC.calls.append({"kind": kind, "error": str(exc)[:300], "seconds": round(time.monotonic() - started, 1)})
            raise
        finally:
            _LAST_CALL_AT[0] = time.monotonic()
        usage = response.get("usage") or {}
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        REC.calls.append({
            "kind": kind, "model": response.get("model"), "content": content,
            "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
            "cost": usage.get("cost"), "seconds": round(time.monotonic() - started, 1),
        })
        return response

    client.chat_completion = chat_completion

    real_build_part = service._build_part

    def build_part(*args: Any, **kwargs: Any):
        part = real_build_part(*args, **kwargs)
        REC.parts.append({
            "intent": part.intent, "resolved_answer": part.resolved_answer,
            "context": part.context, "all_products": part.all_products_for_priority_list,
        })
        return part

    service._build_part = build_part

    real_retrieve = support_lane.retrieve

    def retrieve(query: str):
        passages = real_retrieve(query)
        REC.passages.extend(p.text for p in passages)
        return passages

    support_lane.retrieve = retrieve

    real_validate = service.validate_grounded

    def validate_grounded(answer_text: str, context: Any, **kwargs: Any):
        result = real_validate(answer_text, context, **kwargs)
        REC.guardrail.append({"grounded": result.grounded, "unsupported": result.unsupported_claims, "text": answer_text})
        return result

    service.validate_grounded = validate_grounded

    if not log_usage:
        AIRequestRepository.create = lambda self, **kwargs: None  # type: ignore[method-assign]
        AIRequestRepository.count_today_for_business = lambda self, *a, **k: 0  # type: ignore[method-assign]


def _grounding_universe(intents: tuple[str, ...]) -> dict:
    """Every number the deterministic layers supplied for this turn — the
    only numbers a final answer may contain (besides the question's own
    and the previous answer's)."""
    universe: dict[str, Any] = {"parts": REC.parts, "help_passages": REC.passages}
    if "metric_definition" in intents:
        universe["glossary"] = METRIC_DEFINITIONS
    return universe


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _resolve_owner(db, business_name: str) -> tuple[Business, str, list[Business]]:
    business = db.execute(
        select(Business).where(Business.name == business_name, Business.deleted_at.is_(None))
    ).scalar_one()
    membership = db.execute(
        select(Membership).where(Membership.business_id == business.id, Membership.role == "owner")
    ).scalars().first()
    group = list(
        db.execute(
            select(Business).where(
                ((Business.id == business.id) | (Business.parent_business_id == business.id)),
                Business.deleted_at.is_(None),
            )
        ).scalars()
    )
    return business, str(membership.user_id), group


def _turns(case: dict) -> list[dict]:
    if "turns" in case:
        return case["turns"]
    return [{k: case[k] for k in ("question", "expect", "facts", "all_branches") if k in case}]


def rescore(path: Path, dataset: dict) -> int:
    """Re-scores a saved run's answers with the current scorer and facts —
    zero AI calls. The grounded check needs the contexts the run saw, which
    aren't saved, so its stored result is kept as-is."""
    report = json.loads(path.read_text(encoding="utf-8"))
    specs = {c["id"]: c for c in dataset["cases"]}
    with SessionLocal() as db:
        business, _user_id, group = _resolve_owner(db, dataset["business"])
        env = FactEnv(db=db, business=business, group=group, now=datetime.fromisoformat(report["run"]["as_of"]))
        for case in report["cases"]:
            if case["status"] == "ERROR" or case["id"] not in specs:
                continue
            previous_answer = None
            for turn, spec in zip(case["turns"], _turns(specs[case["id"]])):
                expect = dict(spec.get("expect") or {})
                facts = [f for s in spec.get("facts", []) for f in resolve_fact(env, s)]
                forbid = [str(f.number) for s in expect.pop("forbid_facts", []) for f in resolve_fact(env, s)]
                expect["forbid_numbers"] = [*expect.get("forbid_numbers", []), *forbid]
                score = score_turn(
                    expect=expect, facts=facts, answer=turn["answer"], intents=tuple(turn["intents"]),
                    help_answered=turn["help_answered"], handoff_available=turn.get("handoff_available", False),
                    grounding_context={}, question=turn["question"], previous_answer=previous_answer,
                    ai_calls=len(turn["ai_calls"]),
                )
                score.checks["grounded"] = turn["checks"].get("grounded", True)
                score.reasons = [r for r in score.reasons if not r.startswith("grounded:")]
                turn.update(checks=score.checks, reasons=score.reasons, passed=score.passed)
                previous_answer = turn["answer"]
            case["status"] = "PASS" if all(t["passed"] for t in case["turns"]) else "FAIL"
    report["run"]["label"] = f"{report['run']['label']}-rescored"
    report["run"]["fact_integrity_issues"] = env.integrity_issues
    stem = path.stem + "-rescored"
    (path.parent / f"{stem}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (path.parent / f"{stem}.md").write_text(render_markdown(report), encoding="utf-8")
    passed = sum(c["status"] == "PASS" for c in report["cases"])
    print(f"{passed}/{len(report['cases'])} passed after re-scoring — report: {stem}.md")
    return 0


def run(args: argparse.Namespace) -> int:
    dataset = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if args.rescore:
        return rescore(Path(args.rescore), dataset)
    cases = dataset["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.category:
        cases = [c for c in cases if c["category"] in set(args.category.split(","))]
    if args.failed_from:
        previous = json.loads(Path(args.failed_from).read_text(encoding="utf-8"))
        failed = {c["id"] for c in previous["cases"] if c["status"] != "PASS"}
        cases = [c for c in cases if c["id"] in failed]

    as_of = datetime.fromisoformat(args.as_of or dataset["as_of"])
    if not args.dry_run:
        _install_hooks(pace_seconds=args.pace, log_usage=args.log_usage)

    results: list[dict] = []
    with SessionLocal() as db:
        business, user_id, group = _resolve_owner(db, dataset["business"])
        env = FactEnv(db=db, business=business, group=group, now=as_of)
        started = time.monotonic()
        for index, case in enumerate(cases, start=1):
            case_result = {"id": case["id"], "category": case["category"], "turns": []}
            previous: dict | None = None
            for turn in _turns(case):
                expect = dict(turn.get("expect") or {})
                facts = [f for spec in turn.get("facts", []) for f in resolve_fact(env, spec)]
                forbid = [str(f.number) for spec in expect.pop("forbid_facts", []) for f in resolve_fact(env, spec)]
                expect["forbid_numbers"] = [*expect.get("forbid_numbers", []), *forbid]
                turn_result: dict[str, Any] = {
                    "question": turn["question"], "facts": [asdict(f) for f in facts], "expect": expect,
                }
                if args.dry_run:
                    case_result["turns"].append(_jsonable(turn_result))
                    continue

                for attempt in range(args.retries + 1):
                    REC.reset()
                    db.rollback()
                    answer = service.answer_question(
                        db, business_id=business.id, user_id=user_id, question=turn["question"], now=as_of,
                        all_branches=bool(turn.get("all_branches")),
                        previous_question=previous["question"] if previous else None,
                        previous_answer=previous["answer"] if previous else None,
                        previous_intent=previous["intent"] if previous else None,
                        previous_intents=list(previous["intents"]) if previous else None,
                    )
                    if answer.intent != "provider_unavailable" or attempt == args.retries:
                        break
                    time.sleep(args.retry_wait)

                intents = answer.intents or (answer.intent,)
                score = score_turn(
                    expect=expect, facts=facts, answer=answer.answer, intents=intents,
                    help_answered=answer.help_answered, handoff_available=answer.handoff_available,
                    grounding_context=_grounding_universe(intents), question=turn["question"],
                    previous_answer=previous["answer"] if previous else None, ai_calls=len(REC.calls),
                )
                turn_result.update({
                    "answer": answer.answer, "intents": list(intents), "grounded": answer.grounded, "provider_retries": attempt,
                    "help_answered": answer.help_answered, "checks": score.checks, "reasons": score.reasons,
                    "passed": score.passed, "provider_error": answer.intent == "provider_unavailable",
                    "ai_calls": list(REC.calls), "guardrail": list(REC.guardrail),
                    "parts": [{"intent": p["intent"], "resolved": p["resolved_answer"] is not None} for p in REC.parts],
                })
                case_result["turns"].append(_jsonable(turn_result))
                previous = {
                    "question": turn["question"], "answer": answer.answer, "intent": answer.intent,
                    "intents": intents,
                }

            if args.dry_run:
                case_result["status"] = "DRY"
            elif any(t.get("provider_error") for t in case_result["turns"]):
                case_result["status"] = "ERROR"
            else:
                case_result["status"] = "PASS" if all(t["passed"] for t in case_result["turns"]) else "FAIL"
            results.append(case_result)
            print(f"[{index}/{len(cases)}] {case['id']}: {case_result['status']}"
                  + ("" if case_result["status"] in ("PASS", "DRY") else
                     "  " + "; ".join(r for t in case_result["turns"] for r in t.get("reasons", []))[:300]),
                  flush=True)
        elapsed = time.monotonic() - started

    run_info = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": args.label, "as_of": as_of.isoformat(), "business": dataset["business"],
        "configured_model": get_settings().openrouter_model,
        "fallback_models": get_settings().openrouter_fallback_models,
        "elapsed_seconds": round(elapsed),
        "selection": {"only": args.only, "category": args.category, "failed_from": args.failed_from},
        "fact_integrity_issues": env.integrity_issues,
    }
    report = {"run": run_info, "cases": results}
    if args.dry_run:
        for c in results:
            for t in c["turns"]:
                print(f"  {c['id']}: {t['question']}\n     facts={[(f['label'], f['text'], f['number']) for f in t['facts']]}"
                      f" forbid={t['expect'].get('forbid_numbers')}")
        print("Fact integrity issues:", env.integrity_issues or "none")
        return 0

    REPORTS_DIR.mkdir(exist_ok=True)
    stem = f"ask_orla_eval_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M')}" + (f"_{args.label}" if args.label else "")
    (REPORTS_DIR / f"{stem}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (REPORTS_DIR / f"{stem}.md").write_text(render_markdown(report), encoding="utf-8")
    passed = sum(c["status"] == "PASS" for c in results)
    print(f"\n{passed}/{len(results)} passed — report: tests/ai_eval/reports/{stem}.md")
    return 0


def _summary_numbers(cases: list[dict]) -> dict:
    calls = [call for c in cases for t in c["turns"] for call in t.get("ai_calls", [])]
    questions = sum(len(c["turns"]) for c in cases)
    return {
        "cases": len(cases), "passed": sum(c["status"] == "PASS" for c in cases),
        "failed": sum(c["status"] == "FAIL" for c in cases), "errors": sum(c["status"] == "ERROR" for c in cases),
        "provider_retries": sum(t.get("provider_retries", 0) for c in cases for t in c["turns"]),
        "questions": questions, "ai_calls": len(calls),
        "max_calls_per_question": max((len(t.get("ai_calls", [])) for c in cases for t in c["turns"]), default=0),
        "tokens_in": sum(c.get("tokens_in") or 0 for c in calls),
        "tokens_out": sum(c.get("tokens_out") or 0 for c in calls),
        "cost_usd": sum(Decimal(str(c.get("cost") or 0)) for c in calls),
        "models": sorted({c.get("model") for c in calls if c.get("model")}),
    }


def render_markdown(report: dict) -> str:
    run_info, cases = report["run"], report["cases"]
    s = _summary_numbers(cases)
    scored = s["cases"] - s["errors"]
    rate = (100 * s["passed"] / s["cases"]) if s["cases"] else 0
    lines = [
        f"# Ask ORLA accuracy eval — {run_info['generated_at']}" + (f" ({run_info['label']})" if run_info["label"] else ""),
        "",
        f"- **Pass rate: {s['passed']}/{s['cases']} cases ({rate:.1f}%)** — {s['failed']} failed, {s['errors']} provider errors, {s['provider_retries']} question(s) re-asked after a provider failure"
        + (f"; {100 * s['passed'] / scored:.1f}% of cases that got a provider response" if s["errors"] and scored else ""),
        f"- Business: {run_info['business']} · data as of {run_info['as_of']} · {s['questions']} questions",
        f"- Models that answered: {', '.join(s['models']) or 'n/a'} (configured: {run_info['configured_model']}, "
        f"fallbacks: {run_info['fallback_models']})",
        f"- AI calls: {s['ai_calls']} ({s['ai_calls'] / max(s['questions'], 1):.2f}/question, max {s['max_calls_per_question']}) · "
        f"tokens in/out: {s['tokens_in']:,}/{s['tokens_out']:,} · reported cost: ${s['cost_usd']}",
        f"- Run time: {run_info['elapsed_seconds']}s · selection: {json.dumps(run_info['selection'])}",
        "",
        "## Fact integrity (independent SQL vs app calculation layer)",
        "",
    ]
    issues = run_info.get("fact_integrity_issues") or []
    lines += [f"- {i}" for i in issues] if issues else ["- No disagreements."]

    by_category: dict[str, list[dict]] = {}
    for c in cases:
        by_category.setdefault(c["category"], []).append(c)
    lines += ["", "## By category", "", "| Category | Passed | Cases |", "|---|---|---|"]
    for category, items in by_category.items():
        lines.append(f"| {category} | {sum(i['status'] == 'PASS' for i in items)} | {len(items)} |")

    check_names = ["intent", "behaviour", "facts", "grounded", "leaks", "repeats", "forbidden", "ai_calls"]
    lines += ["", "## Check failure counts (per question)", "", "| Check | Failed |", "|---|---|"]
    for name in check_names:
        failed = sum(1 for c in cases for t in c["turns"] if t.get("checks", {}).get(name) is False)
        lines.append(f"| {name} | {failed} |")

    lines += ["", "## Results", "", "| Case | Category | Intent(s) | Result | Failed checks |", "|---|---|---|---|---|"]
    for c in cases:
        intents = " → ".join(",".join(t.get("intents", [])) for t in c["turns"])
        failed_checks = sorted({k for t in c["turns"] for k, ok in t.get("checks", {}).items() if not ok})
        lines.append(f"| {c['id']} | {c['category']} | {intents} | {c['status']} | {', '.join(failed_checks)} |")

    failures = [c for c in cases if c["status"] != "PASS"]
    if failures:
        lines += ["", "## Failure details", ""]
    for c in failures:
        lines.append(f"### {c['id']} ({c['status']})")
        for t in c["turns"]:
            answer = (t.get("answer") or "").replace("\n", " ⏎ ")
            lines += [
                "",
                f"- **Q:** {t['question']}",
                f"- **A:** {answer[:700]}{'…' if len(answer) > 700 else ''}",
                f"- intents: {t.get('intents')} · checks failed: {', '.join(t.get('reasons', [])) or 'none'}",
            ]
            classify = next((call.get("content") for call in t.get("ai_calls", []) if call["kind"] == "classify"), None)
            if classify:
                lines.append(f"- classify output: `{(classify or '')[:300]}`")
            rejected = [g for g in t.get("guardrail", []) if not g["grounded"]]
            if rejected:
                lines.append(f"- guardrail rejected: {rejected[0]['unsupported']} in `{rejected[0]['text'][:300]}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--category", help="comma-separated categories")
    parser.add_argument("--failed-from", help="a previous run's JSON report — re-run only its non-passing cases")
    parser.add_argument("--label", default="", help="suffix for the report file name, e.g. baseline")
    parser.add_argument("--as-of", help="ISO datetime to answer as of (default: the dataset's as_of)")
    parser.add_argument("--pace", type=float, default=3.5, help="minimum seconds between AI calls (free tier: 20/min)")
    parser.add_argument("--retries", type=int, default=1, help="re-ask a question whose provider call failed")
    parser.add_argument("--retry-wait", type=float, default=20.0)
    parser.add_argument("--dry-run", action="store_true", help="resolve expected facts only; no AI calls")
    parser.add_argument("--log-usage", action="store_true", help="count eval calls against the real daily cap/log")
    parser.add_argument("--rescore", help="a previous run's JSON report — re-score its saved answers, no AI calls")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
