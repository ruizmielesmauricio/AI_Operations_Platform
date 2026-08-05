# 11_Development_Roadmap.md

**Version:** 1.15 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 06/08/2026

---

# Document Contract

## Purpose

This document defines the delivery roadmap at a governance level: the phases, what each phase must produce, and the gates that must be passed before moving on.

It is written to **map directly onto Jira epics** so that this document remains the strategic source of truth while Jira handles day-to-day execution tracking. Each phase below corresponds to an epic; each deliverable corresponds to a story.

**Jira project:** `COP` — https://mauricio-copilot-app.atlassian.net/jira/software/projects/COP/boards/1/timeline

*Note: the Jira instance is private and cannot be read from outside the authenticated session. This document does not attempt to mirror Jira's current state — it defines what the roadmap should contain, so Jira can be populated from it.*

---

## Audience

* Founder
* Engineering Team
* Future Employees
* Investors

---

## In Scope

* Delivery phases and their objectives
* Deliverables per phase, structured as Jira epics and stories
* Milestone gates and exit criteria
* Sequencing rationale

---

## Out of Scope

This document intentionally does **not** define:

* Requirements detail (see `10_Product_Requirements.md`)
* Technical implementation (see `03_System_Architecture.md`)
* Sprint-level task breakdown (lives in Jira)
* Commercial forecasting (see `09_Business_Model.md`)

---

## Related Documents

* 10_Product_Requirements.md
* 15_Customer_Discovery.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

The roadmap deliberately separates **product validation** from **commercial launch**. The founder builds a working prototype and validates it with real bike shops *before* taking on company registration, legal costs, and production billing.

Seven phases, four gates. Nothing proceeds past a gate without evidence, not optimism.

The most important sequencing decision: **customer discovery comes before serious build.** Phase 1 interviews should inform what gets built in Phase 2, not the other way round.

---

# Jira Mapping Convention

| This Document | Jira |
|---|---|
| Phase | Epic |
| Deliverable | Story |
| Acceptance criterion | Story acceptance criteria |
| Gate | Epic-level "Definition of Done" / milestone on timeline |

**Suggested Jira labels:** `phase-0` … `phase-7`, `gate-a` … `gate-d`, `governance`, `backend`, `frontend`, `data`, `ai`, `billing`, `discovery`

---

# Phase 0 — Documentation and Decisions

**Epic:** `COP — Phase 0: Foundation Documentation`
**Status:** Substantially complete

| Deliverable | Status |
|---|---|
| Company Constitution | Complete |
| Project Vision | Complete |
| Operational Domains | Complete |
| System Architecture | Complete |
| Technology Stack | Complete |
| AI Architecture | Complete |
| Database Design | Complete |
| Deployment Guide | Complete |
| Cost Analysis | Complete |
| Business Model | Complete |
| Product Requirements | Complete |
| Development Roadmap | Complete (this document) |
| Decision Register consolidated | Complete |
| Branding Strategy | In progress |
| Repository structure created | Complete |

**Outstanding housekeeping:**

- [x] Consolidate the former decision registers into `12_Decision_Register.md`
- [x] Update `01_Project_Vision.md` to remove the import-template guidance (superseded by PD-006; replaced by the "Low-Friction Use" product principle)
- [x] Update `06_Database_Design.md` and `10_Product_Requirements.md` if ADR-016 is accepted — done 04/08/2026; `10_Product_Requirements.md` reviewed and needed no change (no repairs-specific content exists there)
- [ ] Generate remaining individual decision files in `docs/decisions/` — partially started 04/08/2026: ADR-016, ADR-022, ADR-023 now have files; full historical backfill remains

---

# Phase 1 — Customer Discovery

**Epic:** `COP — Phase 1: Customer Discovery`
**Priority:** Highest. Nothing else matters until this is done.

| Deliverable | Acceptance Criteria |
|---|---|
| Interview script finalised | `15_Customer_Discovery.md` reviewed and ready to use |
| Interview target list built | 25–30 Irish independent bike shops identified with contact details |
| 15–20 interviews completed | Each recorded in `docs/business/interviews/` |
| POS/export formats catalogued | Which systems shops actually use, and what their exports look like |
| Sample data files collected | At least 5 real (anonymised) export files for schema-detection testing |
| Pain point register populated | Top 10 pain points ranked by frequency and severity |
| Assumptions scored | Every assumption in `15_Customer_Discovery.md` marked Validated / Not / Unsure |
| Willingness-to-pay evidence gathered | Test commercial response to the accepted €80/month price |
| Module priority ranked | Which of the five domains customers actually value most |

**Why sample data files matter more than they look:** PD-006 commits the platform to schema-agnostic ingestion. That is impossible to build or test without real, messy export files. Collecting these during interviews is the single highest-value technical output of Phase 1.

---

## Gate A — Problem Validation

Proceed only when:

- Interviews confirm repeated, specific pain points (not vague dissatisfaction)
- Businesses can and will provide usable data
- At least one module shows clear, articulated value
- At least some evidence exists that owners would pay for it

**If Gate A fails:** stop and reconsider the segment or the product, before writing production code.

---

# Phase 2 — Technical Prototype

**Epic:** `COP — Phase 2: Technical Prototype`
**Environment:** Local or private only. No customer data, no billing.

| Deliverable | Notes |
|---|---|
| Repository scaffolding | Backend, frontend, Docker, CI skeleton |
| Authentication | Supabase Auth integration; session verified by API |
| Business creation and template selection | Bicycle shop template first |
| Tenant isolation | Enforced and tested from day one, not retrofitted |
| File upload to object storage | Signed URL flow via R2 |
| **Schema detection engine** | Alias dictionary + structural heuristics; tested against real Phase 1 files |
| Column mapping confirmation UI | Plain language, sample values shown (PR-2.4) |
| Mapping profile persistence | Second upload requires no input (PR-2.5) |
| Validation and normalisation | Deterministic; plain-language errors (PR-2.8) |
| Transactional import | Idempotent, reversible |
| Core KPI calculation | Revenue, gross margin, stock cover, repair turnaround |
| Basic dashboard | ECharts, browser-rendered |
| AI explanation layer | Behind gateway; structured input only |
| Import deletion / undo | PR-2.11 |
| Unit tests for all formulas | ED-007 |
| Tenant isolation integration tests | ED-008 |

**Explicitly deferred from Phase 2:** billing, email, monitoring, multi-user roles, forecasting.

---

## Phase 2/3 Detail — Prototype Build Sequence

The founder-agreed, ordered build checklist for the free-tier prototype (spans Phase 2 and pulls forward a few Phase 3 items — conversational agent, alerts, Stripe test mode — since testing the full service offering end-to-end was judged more valuable at this stage than strictly following the phase boundary). This is the sequence actually followed; update it in place as items complete rather than tracking progress elsewhere.

**Stage A — Foundation**
- [x] A1. Create the database (local Postgres via docker-compose)
- [x] A2. Create the full schema — shared core, canonical entities, bicycle-shop template extension (`06_Database_Design.md`)
- [x] A3. Authentication (Supabase Auth — backend JWT verification + frontend client)
- [x] A4. Business signup + template selection (PR-1)
- [x] A5. Tenant isolation enforcement + automated tests (PR-6.1/6.2, ED-008) — built now, not retrofitted

**Stage B — Getting real data in**
- [x] B6. Upload data interface (signed URL to R2)
- [x] B7. Schema/column detection engine — alias dictionary + structural heuristics, tolerant of any POS export format (PR-2, the "critical section") — supports both `sales` and `inventory` entity types (entity type chosen explicitly at upload time, not auto-detected)
- [x] B8. Clean data — deterministic normalisation, validation, plain-language rejected-row reporting, transactional import, undo (PR-2.6-2.11) — includes SKU/name product matching (auto-create on first sight) and inventory_movements recording per sale, needed for stock-level/popularity tracking; frontend "Run import"/"Undo" trigger UI added, and PR-2.2's manual header-row-picker escape hatch built for files auto-detection can't confidently place — both verified live end-to-end
- [x] B8b. Inventory upload entity type — stock-count snapshot uploads reconcile against derived stock (stock is never stored directly, only summed from `inventory_movements`) by writing a single `adjustment` movement per product equal to `uploaded_count - current_derived_stock`; guards against corruption if a sales import is undone *after* a later inventory reconciliation has baked its effect into a subsequent adjustment (blocked with a clear error instead of silently under/over-counting stock) — verified via automated tests and a live end-to-end browser walkthrough exercising the undo-guard scenario for real
- [x] B8c. Purchases and repairs upload entity types, plus a restock-freshness indicator. **Purchases** — restocking as its own transactional entity type (the `"purchase"` reason on `inventory_movements`, reserved since the model was first designed, now has its first writer): each row an independent `+quantity_received` movement, `unit_cost` (optional) seeds a new product's `cost_price` or overwrites an existing one via a new `ProductRepository.update_cost_price` — the first update path `cost_price` has ever had. **Repairs** — a shop's own workshop log/export ingested the same way as sales, one row per finished repair into `production_events` (`event_type="repair"`, `status="completed"`, no parts-consumed detail in v1); `customer_id`/`performed_by_id` deliberately left NULL, same data-minimisation precedent as sales never getting customer-matching. `run_import`/`undo_import`'s entity-type dispatch refactored from a hardcoded if/else into dispatch tables (pure refactor, no behavior change for `sales`/`inventory`) now that there are four entity types. Found and fixed a real bug during testing: the undo-ordering guard was blocking `repairs` undos unconditionally whenever *any* later inventory reconciliation existed, even though repairs write zero `inventory_movements` and can never be affected by one — narrowed the guard to exempt `repairs`. A new read-only `GET /businesses/{id}/uploads/freshness` endpoint and uploads-page indicator show "last uploaded N days ago" per entity type (no push/email notification — no scheduler exists yet, Stage D17). Verified via the full test suite (239 passing) and a live end-to-end browser walkthrough: uploaded and imported a purchases file (cost seeded/overwritten correctly, `reason="purchase"` movements written) and a repairs file (`production_events` rows, no stock impact), then ran an inventory reconciliation and confirmed the exact undo-guard fix live — undoing the purchases import was correctly blocked (409), undoing the repairs import was correctly allowed, exactly as the bug fix intended.
- [x] B8d. Remap a confirmed-but-not-yet-run upload. Found live: a user testing B8c's purchases/repairs mapping picked the wrong column for a field, confirmed it, and had no way back — `detect-mapping`/`confirm-mapping` refused to run again once `Upload.status` left `"uploaded"`, and the frontend had no button for it anyway. Fix scoped deliberately to `status == "mapped"` (confirmed, not yet run) — an upload whose import already ran can't be remapped even after undo, since the source file is deleted from R2 right after a successful import (ADR-008); that case's recovery stays "re-upload the file," unchanged. `detect_mapping_for_upload` skips the saved-profile auto-reuse fast path on a remap (`upload.status == "mapped"` is itself the signal) — without this, `confirm_mapping`'s own `upsert()` would have already saved the wrong mapping as this source's profile, and reuse would silently reapply the same mistake before the user ever saw the form again. New `ImportRecordRepository.delete_for_upload` replaces the previous attempt's record on a remap, preserving the "exactly one `ImportRecord` per Upload" invariant `get_for_upload`/`map_by_upload_id` both assume. New "Remap" button on the uploads page next to "Run import." Verified via the full test suite (250 passing) and a live browser walkthrough: confirmed a deliberately wrong mapping (SKU/product-name swapped), remapped, confirmed it re-detected fresh rather than reapplying the wrong saved profile, ran the corrected import, and verified the resulting `sale_items` had the right SKU/product name, not swapped.

**Stage C — The actual product value**
- [x] C8b. Schema foundation for multi-vertical calculations (ADR-016, ADR-022, ADR-023) — `repairs`/`repair_parts_used` (bicycle-specific, unused) replaced by the canonical `production_events`/`production_event_inputs`/`production_event_outputs` pattern, covering bike-shop repairs and cafe kitchen production/recipes under one shape; added canonical `inventory_lots` (lot/batch + expiry-date tracking, requested by a real pharmacy prospect) and a pharmacy `prescription_details` template extension. Models + migration only — no repository/service/API/calculation logic yet, that's C9. Verified via the full test suite, the dedicated migration-chain structural test, and applying to local dev Postgres.
- [x] C9. Core calculations — Retail + Financial Performance, unit-tested per formula (PR-3, ED-007). Workshop (repair) profitability deferred until `production_events` gets a real-time entry workflow and starts generating data. Revenue, gross margin (with a PR-3.5/3.6 cost-data-completeness flag and PR-3.6 revenue/profit distinction), and top/bottom-margin products cover Financial Performance; stock cover, sell-through rate, dead-stock detection, and inventory value at cost cover Retail Operations. Pure formulas live in `app/analytics/`, orchestration in `app/application/`, exposed via two new tenant-scoped GET endpoints. Verified via unit tests on every formula plus an integration test against a real (SQLite) database.
- [x] C10. Findings & recommendations engine (PR-4). Six deterministic rules over C9's output (revenue decline, low gross margin, incomplete cost data, products selling at a loss, low stock, dead stock), each producing a `Finding` (evidence, severity, rule version — PR-4.1/PR-4.4) mapped to a `Recommendation` from a fixed approved library (PR-4.2), ranked by severity then a dollar-denominated impact score (PR-4.3). Not persisted — computed on demand, same as C9, via a new `GET /businesses/{id}/analytics/findings`. The `low_stock` rule (`app/analytics/findings.py::evaluate_low_stock`) is deliberately standalone (just a stock-cover list + threshold, no DB/summary object) so C12 reuses it directly instead of reimplementing the threshold logic. Verified via unit tests per rule plus an integration test seeding a scenario that trips every rule at once — which caught a real bug during design (a loss-making product with too few peers to appear in `bottom_margin_products` was being missed; fixed by scanning `top_margin_products` too).
- [x] C11. Charts/dashboard section, browser-rendered from structured API payloads (PR-3.3), with drill-down scoped to the per-product/per-repair breakdown rows the existing analytics endpoints already return (PR-3.4) — full drill-down to individual `Sale`/`SaleItem` rows deferred, no endpoint lists those yet. Also added, since B8c's repairs upload now writes real `price_charged`/`labour_cost` per completed job: a **Workshop Performance** calc mirroring C9's pattern — `ProductionEventRepository.aggregate_completed_repairs_in_range`, `app/analytics/workshop.py` (labour-only profitability, honestly caveated the same way C9 caveats missing cost data — no `ProductionEventInput`/parts-cost writer yet), `app/application/workshop_performance.py`, exposed via `GET /businesses/{id}/analytics/workshop-performance`. Frontend: `frontend/app/dashboard/page.tsx` — Financial Performance, Retail Operations, Workshop Performance, Findings & Recommendations, and Active Alerts sections, a shared period control, ECharts bar charts (`echarts`/`echarts-for-react`, per ADR-010) for margin and stock-cover breakdowns, plain-language metric definitions on hover (PR-3.7) and data-completeness notes (PR-3.5). Extracted the business-selection logic shared with the uploads page into `useBusinessSelector`, and added the first shared nav (`AppNav`) now that there are two real app pages to move between. Verified via the backend test suite (246 passing, including new Workshop unit/integration tests), a clean frontend production build, and a live browser walkthrough against the running Docker Compose stack confirming all five sections render correctly (including a genuinely empty-data business, proving the empty-state paths) with real API responses.
- [x] C12. Low-stock alerts — real-time, deterministic (PD-009, PR-9). Reuses C10's `evaluate_low_stock` rule unmodified — `app/application/alerts.py::refresh_low_stock_alerts` groups touched products by resolved threshold (product override -> category override -> default, `resolve_low_stock_threshold`) and calls it per group. Fires from `app/imports/importer.py`'s existing post-commit points in both `run_import` and `undo_import` (try/except-wrapped, never fails an otherwise-successful import), for exactly the products that import/undo touched. Persisted to the existing `alerts` table with create/update-in-place/resolve state-transition logic (no duplicate alerts for an ongoing condition), exposed via `GET /businesses/{id}/alerts`. Added `low_stock_threshold_days` (nullable) to `Product`/`ProductCategory` and a composite `alerts` index for PR-9.3. **Follow-up flagged, not built here:** no product-management API/UI exists yet to let an owner actually set those threshold columns — the data model and rule resolution are ready, the settings screen isn't. Verified via unit tests (threshold resolution, JSON-evidence conversion) and integration tests (repository CRUD, full create/update/resolve cycle, and a real `run_import`/`undo_import` round-trip creating then resolving a persisted alert).
- [ ] C13. Simple forecasting baseline (seasonal/moving average)
- [ ] C14. Weather data API integration (free tier — relevant to Irish cycling demand)
- [ ] C15. ML forecasting models (weather-enhanced, built on the Stage C13 baseline)
- [ ] C16. Test forecasting model results against held-out data

**Stage D — Reports**
- [ ] D17. Background job runner / scheduler
- [ ] D18. Weekly/monthly report generation (PR-8, PD-007, ADR-019)

**Stage E — The AI layer (deliberately last — it only explains what Stages C/D already calculated)**
- [ ] E19. Set up and connect AI Router (OpenRouter)
- [ ] E20. Test candidate AI models under GDPR/EU compliance
- [ ] E21. Select the quality/price threshold (ADR-015)
- [ ] E22. Code automatic cheapest-model-above-threshold selection
- [ ] E23. AI output-validation guardrail — blocks any numeric claim not present in the structured input (PR-5.3)
- [ ] E24. AI explanation layer (PR-5.1)
- [ ] E25. Conversational agent — business-data Q&A lane (PD-008, ADR-020, PR-5.6)
- [ ] E26. Build support knowledge base content
- [ ] E27. Conversational agent — support lane, with human handoff when unresolved (PR-5.7)

**Stage F — Payments and wrap-up**
- [x] F28. Simulate Stripe payments (test mode — PR-7)
- [ ] F29. Test prototype end-to-end (Gate B checklist, below)
- [ ] F30. Video tutorials — deferred past prototype validation; UI will likely change once tested

---

## Gate B — Prototype Validation

Proceed only when:

- A real (anonymised) customer file imports successfully end-to-end
- Calculated metrics are verifiably correct against manual calculation
- Dashboard findings are understandable to a non-technical reader
- Tenant isolation tests pass
- Schema detection succeeds on a meaningful proportion of real files without manual mapping

---

# Phase 3 — Pilot-Ready MVP

**Epic:** `COP — Phase 3: Pilot-Ready MVP`

| Deliverable | Notes |
|---|---|
| Production deployment | VPS + Coolify per `07_Deployment_Guide.md` |
| Production database | Neon, EU region, backups verified |
| Backup restoration tested | Not assumed — actually tested |
| Monitoring | Sentry + Uptime Kuma |
| Transactional email | Resend: invitations, import results |
| Scheduled reporting | Weekly (Monday) and monthly (1st-of-month) in-app reports — never emailed — per PR-8/PD-007/ADR-019 |
| User roles and permissions | Owner, manager, staff |
| Import history and error recovery | Visible, reversible |
| Stripe test mode | Checkout and webhook flow proven, not yet live |
| Privacy controls | Retention settings, deletion, data export |
| Audit logging | Privileged actions recorded |
| Forecasting module | Simple methods first (seasonal/moving average) |
| Conversational agent — business Q&A lane | Intent classifier + approved deterministic query functions (PD-008, ADR-020); extends Phase 2's AI explanation layer |
| Conversational agent — product/support lane | Retrieval over an approved help-content knowledge base; hands off to human support when unresolved (PR-5.7) |
| Low-stock alerting | Real-time, deterministic, in-app (PD-009, PR-9) |
| Pilot onboarding material | Setup guide, not a template |
| 3–5 pilot businesses recruited | From Phase 1 interview relationships |

---

# Phase 4 — Pilot Validation

**Epic:** `COP — Phase 4: Pilot Validation`
**This is a measurement phase, not a build phase.**

| Metric to Measure | Why It Matters |
|---|---|
| Import success rate | Validates PD-006 (no-template approach) |
| Manual mapping rate | If high, schema detection needs work |
| Time to first value | Onboarding friction indicator |
| Dashboard usage frequency | Are they actually coming back? |
| AI question volume and cost | Validates the €3/customer cost assumption |
| Support requests per customer | The hidden cost that kills solo-founder SaaS |
| Most-used modules | Informs what to build next |
| Recommendation usefulness | Do they act on them? |
| Data quality problems encountered | Real-world ingestion edge cases |
| Willingness to continue paying | The commercial answer |

**Outputs:** revised data model, onboarding, pricing evidence and any future pricing recommendation, metrics, module priority, and support process — plus real numbers to replace the estimates in `08_Cost_Analysis.md` and `09_Business_Model.md`. The current price remains €80/month unless a later accepted decision supersedes BD-005.

---

## Gate C — Pilot Validation

Proceed only when:

- Pilot businesses use the product repeatedly and unprompted
- Support effort per customer is sustainable for one person
- Data import is reliably standardisable
- Customers express genuine willingness to pay

---

# Phase 5 — Company and Commercial Readiness

**Epic:** `COP — Phase 5: Commercial Readiness`
**Deliberately placed after validation, not before.**

| Deliverable |
|---|
| Legal structure and company registration |
| Revenue/tax registration |
| Business banking |
| Accounting setup |
| Insurance |
| Customer contracts and Terms of Service |
| Privacy notice and data-processing terms (GDPR) |
| Production Stripe account |
| Brand identity finalised (see `13_Branding_Strategy.md`) |
| Domain and trademark clearance completed |

---

# Phase 6 — Public Launch

**Epic:** `COP — Phase 6: Public Launch`

| Deliverable |
|---|
| Production billing activated |
| Public pricing published (€80/month, BD-005) |
| Public marketing website live |
| First paying customers onboarded |
| Application health monitoring in place |
| Churn and support tracking |
| Change log maintained |

---

## Gate D — Launch Validation

Proceed only when:

- Billing works end-to-end, verified with a real transaction
- Legal and privacy documents are in place
- Monitoring and backups are proven
- Unit economics are acceptable against real data

---

# Phase 7 — Product Expansion

**Epic:** `COP — Phase 7: Expansion`
**Only after evidence.**

| Deliverable | Trigger |
|---|---|
| Direct POS integrations | Customer demand for the specific POS |
| Automated recurring imports | Manual upload friction proven |
| Second business template | Validated demand in a new vertical |
| ~~Production Events generalisation (ADR-016)~~ | ~~Second template being built~~ — completed early, in Phase 2/3 (Stage C8b, 04/08/2026), once cafe and pharmacy were both being actively scoped simultaneously rather than waiting for Phase 7 |
| Advanced forecasting (e.g. ML models incorporating external signals such as weather — relevant to Irish cycling demand) | Simple methods proven insufficient |
| Multi-location support | Customer with multiple locations |
| Custom/additional report scheduling (beyond the default weekly/monthly cadence in PR-8) | Requested repeatedly |
| Mobile workflows | Usage data shows mobile need |
| Real-time repair-entry screen (staff-facing "log a repair" workflow writing directly into `production_events`, `status="open"` → `"completed"`) | Shops want live workshop tracking, not just the periodic repairs-file upload (Stage B8c) — would also be the natural place to reliably capture `customer_id`/`performed_by_id`, which the upload path deliberately leaves NULL |
| Supplier tracking on purchases (matching/creating `Supplier` records, wiring the currently-unused `suppliers` table to purchase rows) | Shops need per-supplier reporting — deliberately out of scope for Stage B8c's purchases upload v1, mirroring sales' own precedent of not doing customer-matching |

---

# Sequencing Rationale

**Why discovery before build:** the schema-detection engine (the hardest part of Phase 2) cannot be built well without real customer files. Building first means guessing.

**Why validation before company registration:** legal and accounting costs are real and recurring. Incurring them before knowing anyone will pay converts a cheap experiment into an expensive commitment.

**Why billing is deferred to Phase 3:** it adds meaningful complexity and no learning value during prototyping.

**Why forecasting is deferred:** it is the most technically interesting module and the least necessary for proving core value. That combination makes it a classic trap.

---

# Business Perspective

The gates exist to protect founder time and money. Their purpose is to make stopping — or changing direction — a legitimate, planned outcome rather than an admission of failure.

---

# Customer Perspective

Pilot customers should feel like collaborators, not test subjects. Phase 4 should return value to them, not just extract data from them.

---

# Technical Perspective

Tenant isolation and formula testing are built in Phase 2, not added later. Retrofitting either is disproportionately expensive and error-prone.

---

# Commercial Perspective

Revenue is not expected before Phase 6. The scenarios in `09_Business_Model.md` reflect this — modest MRR by month 12 is the realistic base case, not a disappointment.

---

# Current Decisions

* Separate product validation from commercial launch (BD-004, Accepted)
* Customer discovery precedes serious build (Accepted)
* Payments deferred until Phase 3, production billing until Phase 6 (Accepted)
* Jira `COP` is the execution tracker; this document is the strategic source of truth (Accepted)

---

# Risks

* **Skipping or shortening Phase 1** is the most likely and most damaging failure mode. It is tempting because building feels productive and interviewing feels slow.
* Solo-founder capacity means phases will likely take longer than planned; the roadmap deliberately has no fixed dates for this reason.
* Gate criteria can be rationalised away under pressure. They should be assessed honestly, ideally with a second opinion.

---

# Future Improvements

* Add estimated durations per phase once Phase 1 gives a realistic sense of pace.
* Populate Jira epics and stories directly from this document.
* Add a lightweight weekly review checkpoint to catch drift early.

---

# Phase 3 Detail — Scheduled Reporting Implementation

Implementation checklist for the "Scheduled reporting" deliverable in Phase 3's table above.

- [ ] Store and validate each customer's IANA timezone.
- [ ] Build separate weekly and monthly timezone-aware schedules.
- [ ] Implement the reusable cross-industry in-app report template.
- [ ] Implement top/bottom products, revenue, profit, expenses, comparative charts, projections, rule-based recommendations, low-stock warnings, and data-quality warnings.
- [ ] Add in-app notifications that show the seven-day expiry date.
- [ ] Add idempotency using tenant + report type + reporting period.
- [ ] Implement bounded retries and an independent missing-report recovery job.
- [ ] Add persistent-failure alerts and operational audit records.
- [ ] Implement seven-day expiry of the customer-facing report payload.
- [ ] Add explicit on-demand PDF and Word export; do not generate files on the normal schedule.
- [ ] Add tests for daylight-saving changes, timezone boundaries, weekly/monthly date collisions, duplicate prevention, forced recovery, expiry, and inapplicable business-template sections.
- [ ] Meter report compute, recovery attempts, temporary storage, notifications, and requested exports during the pilot.

This work is governed by PD-007 and ADR-019.

---

# Questions Still Open

* How many interviews are genuinely enough before Gate A — 15, or fewer if patterns emerge clearly?
* Should pilot customers be charged during Phase 4?
* Should the second business template be chosen during Phase 4, to inform ADR-016 before Phase 7?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 29/07/2026 | Initial draft; structured for Jira epic mapping. |
| 0.2 | 30/07/2026 | Removed the completed €79-to-€80 housekeeping item and clarified that pilots test the accepted €80/month price. |
| 0.3 | 30/07/2026 | Marked the `01_Project_Vision.md` import-template housekeeping item complete; added Scheduled Reporting to Phase 3 (PD-007/PR-8 baseline weekly/monthly cadence); clarified Phase 7's "Report scheduling" as custom/additional scheduling only; synced version header with revision history. |
| 0.4 | 30/07/2026 | Removed the self-referential "(technical set)" Related Document. |
| 0.5 | 30/07/2026 | Fixed the Phase 3 "Scheduled reporting" line, which incorrectly described email delivery — corrected to match the accepted in-app-only design (PD-007/ADR-019). |
| 0.6 | 30/07/2026 | Renamed "Change 8 Delivery Work — Scheduled Reporting" to "Phase 3 Detail — Scheduled Reporting Implementation" and labelled it as elaboration on the Phase 3 table, so the heading follows this document's Phase/Gate structure instead of an internal work-item name. |
| 0.7 | 30/07/2026 | Added the conversational agent's business Q&A and product/support lanes, and low-stock alerting, to Phase 3 (PD-008, PD-009, ADR-020). Named weather-augmented ML forecasting as the concrete example of Phase 7's "Advanced forecasting" trigger. |
| 0.8 | 30/07/2026 | Added "Phase 2/3 Detail — Prototype Build Sequence": the founder-agreed, ordered 30-item checklist (Stages A-F) actually followed while building the prototype, tracked in place with checkboxes. |
| 0.9 | 03/08/2026 | Marked F28 (Stripe test-mode payments) complete — Checkout, webhooks, Customer Portal, subscription/invoice edge cases, and dispute handling all verified via live Stripe test-mode testing on localhost. |
| 1.0 | 03/08/2026 | Marked B6 (upload interface) and B7 (schema/column detection engine) complete. B7 v1 is scoped to sales transactions only, with entity type chosen explicitly at upload time; alias dictionary + structural heuristics + confirmation UI + mapping-profile reuse (PR-2.1-2.5) all verified via automated tests and a live end-to-end browser walkthrough, including reuse on a second upload from the same source. |
| 1.1 | 03/08/2026 | Marked B8 (clean data / transactional import + undo, PR-2.6-2.11) complete. Includes SKU/name product matching (auto-create on first sight, never falling back from a SKU miss to a name guess) and inventory_movements recording per sale — the previously-missing link needed for stock-level and product-popularity tracking. Verified via automated tests and a live API walkthrough (no frontend trigger UI built yet — flagged as a follow-up). |
| 1.2 | 03/08/2026 | Closed the two follow-ups flagged in 1.1/1.0: (1) added the frontend "Run import"/"Undo" trigger UI, exposing each upload's import summary and rejected-row reasons; (2) built PR-2.2's manual header-row-picker fallback for files where auto-detection can't confidently place the header, including persisting the picked row so B8's import step (which re-detects fresh each time) falls back to it instead of failing on the same file it already needed help with. Both verified via automated tests and a live end-to-end browser walkthrough. |
| 1.3 | 04/08/2026 | Added B8b: the `inventory` entity type (stock-count snapshot uploads), extending B7's detection engine and B8's import/undo pipeline beyond sales-only. Reconciles a snapshot against derived stock via a single adjustment movement per product, and closes an undo-ordering hazard found during design review that could otherwise let undoing a sales import silently corrupt stock after a later inventory reconciliation. Verified via 156 passing automated tests (unit, integration, tenant isolation) and a live end-to-end browser walkthrough that deliberately exercised the undo-guard bug scenario, confirming it is correctly blocked rather than silently succeeding. |
| 1.4 | 04/08/2026 | Added C8b: schema foundation for multi-vertical calculations. Accepted ADR-016 (Production Events, replacing bicycle-specific `repairs`/`repair_parts_used`), added ADR-022 (`inventory_lots`) and ADR-023 (pharmacy `prescription_details`). Checked off the Phase 0 housekeeping item this depended on; retired the now-moot Phase 7 "Production Events generalisation" trigger row (completed early). Schema/migration only — Stage C9 calculation work is next. |
| 1.5 | 04/08/2026 | Marked C9 complete: deterministic core calculations for Retail Operations and Financial Performance (PR-3), reading from `sales`/`sale_items`/`inventory_movements`/`products`. Workshop (repair) profitability intentionally deferred until `production_events` has a real-time entry workflow generating data. Every formula unit-tested (ED-007); verified against a real database via a new integration test. |
| 1.6 | 04/08/2026 | Marked C10 complete: deterministic findings & recommendations engine (PR-4) over C9's output — six rules, an approved recommendation library, impact-based ranking. Deliberately built the `low_stock` rule as a standalone function so C12 can reuse it directly instead of re-deriving the threshold logic; updated C12's line to say so. |
| 1.7 | 04/08/2026 | Marked C12 complete: real-time low-stock alerts (PD-009/PR-9), reusing C10's `evaluate_low_stock` rule unmodified. Fires from the existing import/undo commit points, persists to `alerts` with create/update-in-place/resolve dedup logic, adds per-product/category threshold columns. Flagged PR-9.3's owner-facing threshold configuration UI as a follow-up — no product-management API/UI exists yet to build it against. |
| 1.8 | 05/08/2026 | Added B8c: purchases and repairs upload entity types (the `"purchase"` `inventory_movements` reason, reserved since the model was designed, gets its first writer; repairs are ingested from a shop's own workshop log into `production_events`, same pattern as sales), plus a restock-freshness indicator. Refactored `run_import`/`undo_import`'s entity-type dispatch from a hardcoded if/else into dispatch tables for four entity types. Found and fixed a real bug during testing: the undo-ordering guard was unconditionally blocking `repairs` undos whenever any later inventory reconciliation existed, even though repairs write zero `inventory_movements` and can never be affected by one. Recorded two deferred feature ideas in Phase 7: a real-time repair-entry screen, and supplier tracking on purchases. |
| 1.9 | 05/08/2026 | Marked C11 complete: the first user-facing dashboard, plus a Workshop Performance calc (unplanned but roadmap-consistent, unblocked by B8c's repairs data) so it covers all three operational domains from day one. Charts render browser-side from structured API payloads (ADR-010, ECharts) with drill-down scoped to per-product/per-repair breakdown rows — full raw-record drill-down flagged as a follow-up, no endpoint lists individual sales rows yet. Verified via the backend suite (246 passing), a clean frontend build, and a live walkthrough against the running Docker Compose stack. |
| 1.10 | 05/08/2026 | Added B8d: remapping a confirmed-but-not-yet-run upload, closing a real gap found live (a mapping mistake had no way back short of re-uploading). Deliberately scoped to `status == "mapped"` only — remapping after a completed (even undone) import stays unsupported, since the source file is already deleted from R2 by then (ADR-008); recovery there is still re-upload. Found and fixed a second-order trap while building it: naively allowing remap to re-run the normal saved-profile reuse check would have silently reapplied the very mapping mistake the user was trying to fix, since `confirm_mapping` had already saved it as that source's profile — fixed by skipping the reuse fast path on a remap. Verified via the full test suite (250 passing) and a live walkthrough deliberately swapping SKU/product-name columns, remapping, and confirming the corrected data landed right. |
| 1.11 | 05/08/2026 | Two gaps found using C11's dashboard, fixed: (1) `rank_top_sellers` conflated "makes the most money" with "actually sells the most" — a high-price, low-volume item could outrank a genuinely popular one on revenue alone. Split into `rank_top_sellers_by_units`/`rank_top_sellers_by_revenue`, surfaced as a dashboard filter toggle rather than one ambiguous list. (2) Inventory (stock-count) uploads never touched `Product.cost_price` — only sales-at-creation and purchases did — so any product first seen via an inventory upload showed "Value at Cost: unknown" indefinitely. Added an optional `unit_cost` column to the inventory upload, mirroring purchases field-for-field (same alias list, extracted to a shared constant; same "optional, last value in file wins" semantics; reuses `ProductRepository.update_cost_price`). Verified via the backend suite (258 passing), a clean frontend build, and a live walkthrough confirming the units/revenue toggle produces genuinely different rankings against real data. |
| 1.12 | 05/08/2026 | Flipped sales import precedence: `total_amount` (what was actually charged) now wins over `unit_price × quantity` whenever both are mapped and disagree — previously the reverse, which silently discarded the file's total in favour of a derived figure. Real-world impact this fixes: a POS export's "total" is very often tax-inclusive while "unit price" isn't, so *every* row would mismatch and get silently overridden to the pre-tax figure; the warning read as a data-quality problem when it usually wasn't. Reworded the warning to explain the likely tax cause. Also added a `quantity <= 0` rejection for sales rows (mirrors purchases' `non_positive_quantity`, reworded to entity-agnostic wording since the message template is shared) — closes a `ZeroDivisionError` crash risk this change made far more reachable (division by quantity now happens whenever `total_amount` is present, not only when `unit_price` is absent). **Known limitation, not solved here:** `cost_price_at_sale` is untouched by this change and is typically tax-exclusive (a supplier cost), so gross margin is now computed against revenue that may include tax when `total_amount` was the winning source — margin % can read a few points higher than the true economic margin for shops whose exports include tax in "total." Proper VAT-aware margin (a distinct net-amount/tax-rate field) is future scope. Verified via the backend suite (260 passing). |
| 1.13 | 05/08/2026 | Closed v1.12's flagged limitation: added an optional `tax_amount` field to the sales upload (mirrors `cost_price_at_sale`'s exact shape — new nullable `sale_items.tax_amount` column). `app/analytics/financial.py`'s `GrossMarginResult` gains `net_gross_profit`/`net_gross_margin_pct`, computed only over lines where both cost *and* tax are known (never blending an uncertain line into a "confirmed net" figure), plus `tax_data_coverage_pct` — the same PR-3.5 completeness pattern used everywhere else, one level stricter. The dashboard shows one headline "Gross margin" number: the net figure whenever any tax data exists, falling back to the original tax-inclusive figure with an honest caveat when it doesn't — never two competing percentages. Also sharpened the `total_amount_mismatch` check to account for a known `tax_amount`, so a shop that maps price + tax + total together sees the warning mostly disappear, since tax was the actual explanation for it. Verified with a controlled scenario showing the real gap this closes: 50.0% tax-inclusive margin vs. 38.5% true net margin on the same data. **Explicitly not built:** Workshop Performance's `price_charged` (repairs) has the identical tax exposure but wasn't part of the report that prompted this; same fix pattern applies later. Verified via the backend suite (267 passing) and a clean frontend build. |
| 1.14 | 05/08/2026 | Found and fixed a real revenue-accuracy bug in B7's detection engine (`app/imports/detection.py`), surfaced by a pilot's actual test file (a POS export with both a pre-tax `Subtotal` column and a genuine post-tax `Total Amount` column): layer 1's alias matching was strictly first-column-wins, and `"subtotal"` is a listed synonym for our `total_amount` field — since `Subtotal` sat to the left of `Total Amount` in the file, it silently claimed the `total_amount` mapping, leaving the real total unmapped and revenue understated by the tax amount on every row. Fixed with a new sub-pass: an exact canonical-name match (a column literally called `total_amount`/`Total Amount`) is now claimed *before* any alias/synonym match is considered, regardless of column order — a structural fix that protects all four entity types (sales/inventory/purchases/repairs) against this whole class of alias-shadowing bug, not just this one instance. Also, prompted by the same investigation: reworded the sales/repairs field-mapping labels to explicitly say "charged to the customer" vs. "what YOU paid" (the two were being read backwards), added a framing note above the mapping form, and updated the `total_amount_mismatch` warning to also name per-line discounts as an expected, harmless cause (confirmed: `total_amount` already correctly absorbs any discount since it's trusted as-is, so a discount-driven mismatch needs no fix, just correct labelling — no discount field was added). Verified via a new regression test reproducing the exact bug shape, the full backend suite (268 passing), and a clean frontend build. |
| 1.15 | 06/08/2026 | Closed a data-accuracy gap raised directly (a client accidentally re-uploading an overlapping export would silently double-count revenue/stock/workshop income — nothing checked a new file against what was already imported). Sales' existing `order_reference` is now checked against every previously-imported sale for the business before a group is written; two new optional fields, `purchase_reference` and `repair_reference`, do the same for purchases and repairs (which had no reference field at all before this). A row/group reusing an already-used reference is rejected outright (`duplicate_reference`, in the existing rejection summary — never silently imported), including within a single file (a second occurrence of the same PO/job number later in the same upload). Undoing an import correctly frees its references for reuse with no extra code, since undo deletes the underlying rows entirely. Inventory (stock-count) uploads were deliberately left out of this — reconciliation there is already idempotent by design against *current* stock, not a per-file transaction log, so there's no equivalent "re-imported the same file twice" hazard to close. **Known, stated limitation, not solved here:** a row with no reference at all (most real-world exports today) has no reliable natural key — a genuine repeat sale and an accidental duplicate look identical, and no heuristic (date+product+price matching) was added, since it would misfire on real repeat transactions. Verified via the backend suite (281 passing), a clean frontend build, and a live walkthrough against the running Docker stack: uploaded a sales file, re-uploaded an overlapping one (rejected, revenue unchanged), undid the first, then confirmed the same reference re-imports successfully. |
