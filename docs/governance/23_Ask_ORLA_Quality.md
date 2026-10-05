# 23_Ask_ORLA_Quality.md

**Status:** Living document — re-run and update after any change to Ask ORLA's prompts, routing or data
**Created:** 06/10/2026
**Related:** `21_Pilot_Launch_Plan.md` (item A5), `backend/app/ai/eval/`, `backend/app/ai/orla_constitution.md`

---

# Why this exists

Ask ORLA must answer an owner's questions well *before* the two pilot testers use it, without ever inventing a number (CLAUDE.md core rule: deterministic Python calculates, AI only explains). "Works when I try it" is not enough, so there is now a **question bank** (243 realistic questions) and an **automated scorer** that asks them all and records what happened.

# What is measured

Each question has the routing ORLA should choose (which data answers it) and a kind:

| Kind | A pass means |
|---|---|
| Answer | Routed to the right data, answered, every number traced to the data, no raw codes or markup leaked, and (for the plain "what's my revenue / profit margin" questions) the answer states the figure the dashboard shows |
| Decline | Refused safely: no invented figures, nothing about its own instructions leaked, still polite |
| Definition | Answered from the fixed glossary with **zero** AI cost |

Failures are classed so they can be fixed: wrong routing, declined a valid question, answered one it should decline, answer rejected by the number check, leaked internals, missing figure. **Provider outages (rate limits) are counted separately** — they are infrastructure, not answer quality.

The 243 questions cover: sales and profit (30), stock and best sellers (28), what to reorder / forecast (19), recommendations (14), reports (8), plain-English definitions (24), single-product lookups incl. products that don't exist (14), purchases (14), repairs (12), categories (12), weather (16), several questions at once (10), follow-ups (9), things ORLA must decline — other topics, tax/legal advice, changing data, other shops' data, prompt-injection attempts, "pretend my revenue was…" (23), and casual wording / typos / other languages (10).

# How to run it

```bash
# Free, instant, no AI provider — checks the plumbing for every question
docker compose exec backend python -m app.ai.eval --mode offline --business-id <uuid> --fresh

# Real AI, in batches that fit a free allowance; saved after each question, safe to stop and resume
docker compose exec backend python -m app.ai.eval --mode live --business-id <uuid> --max-calls 100

# After a fix: re-run only what failed or hit a provider limit
docker compose exec backend python -m app.ai.eval --mode live --business-id <uuid> --redo-failed

# Re-judge saved answers after editing the bank (no AI calls)
docker compose exec backend python -m app.ai.eval --mode live --business-id <uuid> --rescore
```

Questions fill in real product, category, supplier, order and repair names from the business under test, and are asked "as of" the day after its last sale so a business with older data still gets real answers. Results go to `backend/eval_results/` (not committed).

# Results (06/10/2026, free model, Test Bike Shop)

| Run | Pass rate (questions that completed) |
|---|---|
| Offline plumbing check, all 243 | 243 / 243 |
| First live run, before any fix | **216 / 240 = 90%** |
| After the fixes below | **242 / 243 ≈ 99.6%** |

The free model is not perfectly repeatable: a re-run can move one or two questions either way. Treat 98-99% as the real figure and re-measure after every change.

# What the first live run found, and what was done

| Finding | Fix |
|---|---|
| The model **did arithmetic** (a sales drop in euro, the total value of unsold stock, "165 more not shown"), which the number check rightly rejected — the owner got a generic "couldn't answer" | ORLA's data now includes those figures **computed in code**: the euro change in sales, the count and total value of unsold stock, the number of sales and the average sale. The explainer is told never to add, subtract or turn a ratio into a percentage |
| When the number check rejected an answer, the owner got nothing useful | **One corrective retry**: the model is shown exactly which figures weren't in the data and asked again. The retry passes the identical check; if it still fails, the honest fallback is shown. Never a loop, at most one extra call on the ~7% of questions that need it |
| "What does gross margin mean **and** what is mine?" answered only the definition — the second half was silently dropped | Compound questions now go to the classifier so both parts are answered |
| "What's running low?" returned a glossary definition instead of the data | Glossary shortcut tightened (a bare "what is X" only counts when the question ends at the term) |
| "How many sales did I make?", "average sale" had no data behind them | Sale count and average sale added (one tested formula shared with reports) |
| "Sales this month vs last month", "how busy will I be next week", "why is it like that?" were sometimes declined | Routing guidance added, plus a deterministic recovery for short "why" follow-ups |
| Definitions and the "I can't help" reply used analyst words | Rewritten in the plain wording used on the screens; new terms (profit margin, reorder level, days of stock left, share of stock sold, product code, delivery time) are recognised |
| The model rounded ("49%" for 49.2%) | Constitution v2: copy numbers exactly, no "about/roughly", use the screens' plain names |

# Known gaps (not fixed yet)

- "Which supplier did I spend the most with?" — the per-supplier spend totals shown on the Suppliers page are not yet given to Ask ORLA, so it can't state the total (it declines).
- "How fast is my stock turning over?" — stock turnover only exists in the reports, so ORLA answers with the closest figure it has (share of stock sold) and says so.
- The free model occasionally times out or runs out of its allowance mid-run; the scorer pauses and resumes.
- The bank tests a bike-shop dataset. The routing is generic, but a second trade's data should be run through the same bank before ORLA is offered to it.

# Next

1. **When the pilot starts:** switch to a paid model (about $0.0002 per question) and re-run the bank to compare.
2. **A log of real unanswered questions** from the testers is the best way to grow this bank. Storing question text is personal-data handling, so it waits for the founder's legal session; until then, the testers can send questions that failed.
3. Re-run after every prompt, routing or data change; keep the pass rate in the table above.

# Revision History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 06/10/2026 | Question bank, scorer, first live measurements and fixes. |
