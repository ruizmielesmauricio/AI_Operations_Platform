---
name: business-formula
description: Use when writing or changing a business calculation, metric, or aggregation (profit, inventory, forecasting inputs, KPIs, etc.) anywhere under backend/app/analytics/ or backend/app/domain/. Enforces the Core Rule (Business Logic First) and ED-007 (every business formula requires unit tests before the feature is complete).
---

Governed by: `CLAUDE.md` (Core Rule), `docs/governance/12_Decision_Register.md` ED-006/ED-007.

1. **Placement.** The calculation is deterministic Python, not a prompt. It lives in
   `backend/app/analytics/` (or `app/domain/` if it's a core business rule), never inside
   `backend/app/ai/`. The AI layer may only receive an already-computed number and explain it in
   words — it must never compute, aggregate, validate, or invent the number itself.
2. **Money.** Any monetary value uses `Decimal`, never `float`. Check the diff for stray `float()`
   casts or literals like `0.1` on a money path before calling it done.
3. **Time.** Store and compute in UTC; only convert to the business's timezone (`Business.timezone`,
   see `app/models/business.py`) at the presentation edge.
4. **Tenant scoping.** The function must operate on data already filtered by `business_id` — pass in
   a pre-scoped queryset/dataframe, don't have the formula itself decide which business's rows to
   pull.
5. **Tests (non-negotiable, ED-007).** Add a unit test under `backend/tests/unit/` covering: the
   normal case, an empty/zero-input case, and one rounding/boundary case if money or percentages are
   involved. The feature is not done until this test exists and passes — do not report completion
   without it.
6. **Definition of done.** Formula implemented + test added and green + no float arithmetic on money
   + no calculation logic leaked into `app/ai/` or the frontend.
