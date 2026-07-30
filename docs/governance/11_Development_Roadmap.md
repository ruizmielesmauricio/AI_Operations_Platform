# 11_Development_Roadmap.md

**Version:** 0.5 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

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
- [ ] Update `06_Database_Design.md` and `10_Product_Requirements.md` if ADR-016 is accepted
- [ ] Generate remaining individual decision files in `docs/decisions/`

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
| Production Events generalisation (ADR-016) | Second template being built |
| Advanced forecasting | Simple methods proven insufficient |
| Multi-location support | Customer with multiple locations |
| Custom/additional report scheduling (beyond the default weekly/monthly cadence in PR-8) | Requested repeatedly |
| Mobile workflows | Usage data shows mobile need |

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

# Change 8 Delivery Work — Scheduled Reporting

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
