# ADR-028: The support lane answers only from versioned help articles, retrieved deterministically and verified after generation, with a recorded human handoff

**Status:** Accepted (implemented)
**Date:** 2026-11-13
**Related:** PD-008, ADR-020, PR-5.6, PR-5.7, roadmap E26/E27, Jira ORLA-67, `backend/app/support/`, `backend/app/ai/support_lane.py`, `backend/app/ai/support_guard.py`, migration `a7c3e9f1b2d4`

## Context

PD-008/ADR-020 gave Ask ORLA three lanes; only business-data Q&A existed. Shop owners also ask how to use ORLA ("how do I upload my stock count?"). Those answers must be as trustworthy as the numbers: an invented step or button is as harmful as an invented figure, and AI cost must stay bounded (no extra AI round-trip beyond classify + explain).

## Decision

1. **Help content is code.** 27 Markdown articles in `backend/app/support/content/`, one per feature area, with front-matter (`slug`, `title`, `category`, `order`, `summary`, `keywords`, `version`, `updated`). Each `## ` section is one retrievable passage. Content changes ship and are reviewed like source code; a test fails if a feature area loses its article or the business-type list drifts from the registry.
2. **The classifier picks the lane.** A new `product_help` intent in the existing single classify call. Defence in depth only promotes an `out_of_scope` verdict to `product_help` when the question is how-to shaped *and* retrieval is confident — never the other way.
3. **Retrieval is deterministic.** A field-weighted BM25 ranker over passages (`knowledge_base.py`): no embeddings, no vendor, no network, same result every time, also used by the Help page search. Below a confidence bar (score ≥ 6, or ≥ 4 with every question word matched) the lane refuses without an explain call.
4. **One explain call, JSON out, verified after.** The model gets only the retrieved passages and `orla_support_constitution.md`, and returns `{answerable, answer, passage_ids}`. `support_guard.verify_support_answer` then requires real citations, no links, every number and every quoted UI label present in the cited passages, and ≥ 75% of the answer's meaningful words drawn from them. Any failure discards the answer and offers the handoff. Article links are built by code from cited passage ids, never from model text.
5. **Zero-AI fallbacks.** The help part of a compound question, and how-to questions while the provider is down, get the best article's reviewed summary and link — no AI at all.
6. **Human handoff is a tenant-scoped record.** "Contact support" creates a `support_requests` row (question, requester, source, ORLA's reply, article slugs — no business data), an audit event (no question text) and an owner-only Support notification, in one transaction. Idempotent per person/question for 24 hours; 10 requests per business per day. The operator reads and resolves requests with `scripts/support_requests.py`; there is no cross-tenant HTTP route.
7. **Email later, no backfill.** `SUPPORT_INBOX_EMAIL` + the existing Resend settings turn on an operator email after commit; until then `operator_notified_at` stays NULL and nothing is lost.

## Consequences

- Cost per help question: classify + explain at most; unanswerable questions cost the classify call only. Logged under `ai_requests.lane = "support"`.
- The verifier will occasionally reject a correct but loosely-worded answer; the user then gets the handoff and the article link. Accepted: a false refusal is cheaper than an invented step.
- Retrieval quality depends on article wording and keywords; new features need an article (enforced by test) and should add likely phrasings to `keywords`.
- Help articles are public (`GET /help/articles`), so they must never contain tenant or internal information.

## Alternatives Considered

- **Embeddings / vector search:** better recall on unusual phrasings, but adds a vendor or model, cost per question and non-determinism for 27 articles. Rejected for now.
- **Answer directly from the whole help corpus in the prompt:** larger prompts every time and no per-passage citation to verify. Rejected.
- **A second AI call to judge groundedness:** breaks the classify + explain cost bound and is itself unverifiable. Rejected in favour of deterministic checks.
- **Email-only handoff:** would lose requests while Resend is not configured. Rejected.

## Review Trigger

More than ~60 articles, frequent false refusals in the `support` lane logs, or pilots asking questions the lexical ranker misses — then reconsider embedding retrieval behind the same verifier.
