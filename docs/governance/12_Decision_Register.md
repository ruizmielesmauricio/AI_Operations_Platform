# 12_Decision_Register.md

**Version:** 1.7
**Status:** Accepted
**Phase:** Company Governance
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---

# Document Contract

## Purpose

This is the **single canonical register** of all significant business, product, architecture, and engineering decisions.

It supersedes and merges two previously conflicting registers:

* `11_ADRs.md` (technical documentation set)
* the former governance register, previously named `12_Architecture_Decision_Log.md`

Both prior registers used overlapping ID numbers for different decisions, and one contained a duplicate ID. All decisions from both have been preserved here under a single, non-conflicting numbering scheme, with prior IDs recorded for traceability.

The former governance register has been renamed to this canonical `12_Decision_Register.md`. The separate `11_ADRs.md` register should be deleted or marked Superseded to prevent conflicting instructions existing in the repository (per `06_Development_Rules.md`, "Do not leave conflicting instructions in different documents").

---

## Audience

* Founder
* Product Team
* Engineering Team
* Future Employees
* Investors

---

## Related Documents

* 00_Company_Constitution.md
* All documents in `docs/governance/` and `docs/technical/`
* Individual decision files in `docs/decisions/`

---

# Decision Types

| Type | Meaning |
|---|---|
| **BD** | Business Decision — pricing, customers, positioning, market strategy |
| **PD** | Product Decision — features, workflows, UX, product capabilities |
| **ADR** | Architecture Decision — technology, infrastructure, software architecture |
| **ED** | Engineering Decision — coding standards, testing, deployment, practices |

# Status Values

| Status | Meaning |
|---|---|
| Proposed | Under discussion, not yet binding |
| Draft | Being documented |
| Accepted | Official company decision |
| Implemented | Built and running in production |
| Superseded | Replaced by a newer decision |
| Rejected | Considered but not adopted |
| Deprecated | No longer recommended |

---

# Conflicts Resolved in This Merge

| Issue | Resolution |
|---|---|
| Two registers both used `ADR-001`–`ADR-004` for different decisions | All renumbered into one sequence; prior IDs noted per decision |
| `12_Architecture_Decision_Log.md` contained **two** decisions numbered `ADR-004` (Neon/Supabase Auth, and Stripe billing) | Split into `ADR-013` (Neon + Supabase Auth) and `ADR-011` (Stripe) |
| `BD-001` meant "€79 price" in one register and "target bike shops" in the other | Bike shops = `BD-001`; pricing now `BD-005` at €80 |
| `PD-001` meant "start with bike shops" in one register and "five operational domains" in the other | Bike shops = `PD-001`; domains = `PD-002` |
| Price recorded as **€79** (Proposed) | **Superseded — now €80/month, Accepted** (`BD-005`) |

---

# Business Decisions (BD)

| ID | Decision | Status | Prior ID |
|---|---|---|---|
| BD-001 | Target independent bike shops as the first commercial vertical | Accepted | gov BD-001 |
| BD-002 | Build a reusable multi-industry platform rather than a bike-shop-only application | Accepted | gov BD-002 |
| BD-003 | Company tagline: *"AI: Helping small businesses make enterprise decisions."* | Accepted | gov BD-003 |
| BD-004 | Validate the product with real customers before completing the full commercial launch process | Accepted | tech BD-002 |
| BD-005 | **Set the current subscription price at €80 per month per business** | **Accepted** | supersedes tech BD-001 (€79, Proposed) |
| BD-006 | Position the product as a complement to the customer's existing POS, not a replacement | Accepted | new |
| BD-007 | **Set the additional-branch/location add-on subscription price at €30 per month per branch** — a branch is billed as its own separate subscription (not a quantity line item on the primary shop's), reusing the exact same Stripe Checkout/webhook/cancel path as the primary €80/month subscription (BD-005) | Accepted | new |

---

# Product Decisions (PD)

| ID | Decision | Status | Prior ID |
|---|---|---|---|
| PD-001 | Start with bicycle shops but design for multiple business types | Accepted | tech PD-001 |
| PD-002 | Organise the platform around five operational domains (see reconciliation in `02_Operational_Domains.md`) | Accepted | gov PD-001 + tech PD-002 |
| PD-003 | Workshop/Production Operations is part of Version 1 | Accepted | gov PD-002 |
| PD-004 | Every feature must save time, save money, reduce operational risk, or improve decisions | Accepted | gov PD-003 |
| PD-005 | Begin with CSV and Excel uploads before building POS integrations | Accepted | tech PD-003 |
| PD-006 | Do not require customers to use a predefined import template; the platform performs schema detection and normalisation | Accepted | from `10_Product_Requirements.md` |
| PD-007 | Generate separate weekly and monthly performance reports, delivered **in-app only — never by email** — as seven-day views with notifications; use a reusable deterministic template and offer PDF/Word only on explicit request | Accepted | new |
| PD-008 | Extend the in-app AI agent to handle three categories of natural-language question through one chat interface — tenant business-data Q&A, scheduled-report explanation, and product/support help — with AI restricted in every case to classifying intent and phrasing an answer, never calculating or inventing one | Accepted | new |
| PD-009 | Add low-stock alerting as a standalone, real-time in-app notification capability, generated deterministically whenever inventory data changes, independent of the weekly/monthly report cycle | Accepted | new |
| PD-010 | Support pharmacies as a third business vertical; minimise personal/health data captured in the schema per Company Constitution Principle 7 ("Customer Data Is Sacred"). Full GDPR special-category compliance (legal basis, DPIA, retention/deletion policy) remains open — see Q-053 | Accepted | new |

---

# Architecture Decisions (ADR)

| ID | Decision | Status | Prior ID |
|---|---|---|---|
| ADR-001 | Use a shared multi-tenant platform rather than separate systems per industry | Accepted | tech ADR-001 |
| ADR-002 | Use business templates for industry-specific configuration | Accepted | tech ADR-002 |
| ADR-003 | Use PostgreSQL as the primary system of record | Accepted | tech ADR-003 |
| ADR-004 | Prefer Next.js and TypeScript for the web application | Accepted | tech ADR-004 |
| ADR-005 | Prefer FastAPI and Python for the backend | Accepted | tech ADR-005 |
| ADR-006 | Keep the platform AI-provider agnostic | Accepted | tech ADR-006 + gov ADR-001 |
| ADR-007 | **Business Logic First** — use deterministic code for all calculations and chart data; AI explains only | Accepted | tech ADR-007 + gov ADR-002 |
| ADR-008 | Use temporary object storage for uploads and delete files after ingestion by default | Accepted | tech ADR-008 |
| ADR-009 | Avoid AWS-specific services in the initial low-cost architecture | Accepted | tech ADR-009 |
| ADR-010 | Render normal dashboard charts in the browser from structured API data | Accepted | tech ADR-010 |
| ADR-011 | Use Stripe for subscription billing, supporting cards and SEPA Direct Debit, with Stripe Tax enabled on Checkout for automatic EU VAT calculation | Accepted | tech ADR-011 + gov ADR-004(b) |
| ADR-012 | Use a shared database with tenant-scoped rows initially | Accepted | tech ADR-012 |
| ADR-013 | Use Neon for managed PostgreSQL and Supabase Auth for identity only (auth-only, not database or storage) | Accepted | gov ADR-004(a) |
| ADR-014 | Separate the platform into specialised engines: Database, Calculation, Machine Learning, AI | Accepted | gov ADR-003 |
| ADR-015 | Route AI requests through OpenRouter behind the internal AI Provider Gateway, selecting cost-effective, EU-compliant models above a defined quality threshold | **Proposed** | new |
| ADR-016 | Generalise repairs and recipes into a shared canonical "Production Events" entity (`production_events`/`production_event_inputs`/`production_event_outputs`) rather than industry-specific tables | Accepted | new |
| ADR-017 | Use Cloudflare R2 (S3-compatible) for object storage | Accepted | from `04_Technology_Stack.md` |
| ADR-018 | Deploy via Docker containers to a low-cost VPS, with managed services for stateful components | Accepted | from `07_Deployment_Guide.md` |
| ADR-019 | Run timezone-aware weekly and monthly reporting as separate idempotent background jobs with retries, independent missing-report recovery, in-app notifications (no email), and seven-day customer-facing retention | Accepted | new |
| ADR-020 | Route every conversational-agent question through an intent classifier that selects one of a fixed, approved set of deterministic query functions or an approved help-content knowledge base before any AI generation occurs — no free-form calculation, retrieval, or invention outside these approved sources | Accepted | new |
| ADR-021 | Do not use Stripe Connect — the platform only charges its own tenants a subscription fee; it does not route payouts to them or facilitate payments between tenants and their customers. Revisit only if a marketplace/payout feature is explicitly planned | Rejected | new |
| ADR-022 | Add a canonical `inventory_lots` (lot/batch + expiry-date) extension to the inventory layer, with a nullable `inventory_lot_id` FK on `inventory_movements` — not pharmacy-specific, since perishables/consumables recur across verticals | Accepted | new |
| ADR-023 | Add a pharmacy `prescription_details` business-template extension table hanging off `sale_items` (prescription number, prescribing doctor, controlled-substance schedule) — deliberately excludes patient identity/clinical fields | Accepted | new |

---

# Engineering Decisions (ED)

| ID | Decision | Status | Prior ID |
|---|---|---|---|
| ED-001 | Documentation before implementation | Accepted | gov ED-001 |
| ED-002 | Every design document follows the company documentation standard | Accepted | gov ED-002 |
| ED-003 | Every document begins with a Document Contract | Accepted | gov ED-003 |
| ED-004 | One document, one responsibility | Accepted | gov ED-004 |
| ED-005 | Deployment must stop automatically when tests fail | Accepted | from `06_Development_Rules.md` |
| ED-006 | No AI provider or router SDK may be referenced outside `backend/app/ai/` | Accepted | from `05_AI_Architecture.md` |
| ED-007 | Every business formula requires unit tests before the feature is considered complete | Accepted | from `06_Development_Rules.md` |
| ED-008 | Tenant isolation must be covered by dedicated integration tests | Accepted | from `06_Development_Rules.md` |
| ED-009 | AI may suggest column mappings but must not clean, validate, transform, or deduplicate customer data | Accepted | from `10_Product_Requirements.md` |

---

# Decisions Requiring Action

| ID | Status | What's Needed to Move to Accepted |
|---|---|---|
| ADR-015 (OpenRouter) | Proposed | Define a numeric quality/reliability threshold and evaluation test set (`05_AI_Architecture.md`, Model Evaluation) |

---

# BD-005 Consistency Status (€80 Price)

€80 per month per business is the accepted current subscription price. The former €79 planning assumption is superseded and must not be used in governance documents, revenue calculations, financial modelling, or customer-facing pricing.

Customer discovery and pilot evidence may inform a future pricing decision, but they do not make BD-005 provisional. Any later change must be recorded as a new accepted decision that explicitly supersedes BD-005.

---

# BD-007 Consistency Status (€30 Branch Add-on)

€30 per month per additional branch/location is the accepted add-on price (BD-007), separate from and additive to BD-005's €80/month primary-shop price — an account with one primary shop and one branch pays €80 + €30 = €110/month total, as two independent Stripe subscriptions, not one combined line item. Implemented and live in Stripe test mode as of `11_Development_Roadmap.md` v1.37; not yet validated by any real paying branch customer.

---

# ADR Template

```markdown
# ADR-XXX — Title

## Status
Proposed | Accepted | Implemented | Superseded | Rejected | Deprecated

## Context
What problem or constraint requires a decision?

## Decision
What was decided?

## Consequences
What becomes easier, harder, cheaper, more expensive, or constrained?

## Alternatives Considered
What other options were reviewed, and why were they not chosen?

## Review Trigger
What evidence would cause this decision to be revisited?
```

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 29/07/2026 | Merged `11_ADRs.md` and the former `12_Architecture_Decision_Log.md` into one canonical register; renamed it `12_Decision_Register.md`; resolved duplicate ADR-004; set price to €80 (BD-005); added ADR-015 through ADR-018 and ED-005 through ED-008. |
| 1.1 | 29/07/2026 | Added accepted decisions PD-006 (no required customer-facing import template) and ED-009 (AI limited to suggesting column mappings). |
| 1.2 | 30/07/2026 | Clarified BD-005 as the accepted current subscription price of €80/month and removed obsolete €79 update actions. |
| 1.3 | 30/07/2026 | Added PD-007 (weekly/monthly automated email reporting, later superseded — see 1.4). Fixed stale filename references left over from the register merge (`08_Tech_Stack.md` → `04_Technology_Stack.md`; `05_AI_Strategy.md` → `05_AI_Architecture.md`; `04_Database.md`/`09_Product_Modules.md` → `06_Database_Design.md`/`10_Product_Requirements.md`). |
| 1.4 | 30/07/2026 | Redefined PD-007 and added ADR-019: scheduled reporting is delivered in-app only (not by email), with seven-day availability, on-demand PDF/Word export, idempotent generation, and recovery controls. |
| 1.5 | 30/07/2026 | Normalized the Prior ID column for PD-007/ADR-019 to match this register's citation convention (`new`, not a work-item name). Corrected `03_System_Architecture.md`, `07_Deployment_Guide.md`, `08_Cost_Analysis.md`, `10_Product_Requirements.md`, and `11_Development_Roadmap.md`, which still described PD-007 as email-delivered after the 1.4 redefinition — all now consistently state in-app-only delivery. Resolved a duplicate "PR-4" section ID in `10_Product_Requirements.md` created when the 1.4 reporting spec was added alongside the existing PR-8. Fixed this table's own out-of-order/duplicate version numbering (the prior 1.3 row appeared twice, once out of chronological order). |
| 1.6 | 30/07/2026 | Added PD-008 (three-lane conversational agent: business Q&A, report explanation, product/support help), PD-009 (standalone low-stock alerting), and ADR-020 (intent-classifier routing to approved deterministic queries or an approved help-content knowledge base — no free-form AI calculation or invention). Recorded during Phase 2 prototype service scoping. |
| 1.7 | 30/07/2026 | Clarified ADR-011 to explicitly cover Stripe Tax (automatic EU VAT on Checkout), recorded during initial `backend/app/billing/` implementation. Added ADR-021 (Rejected): Stripe Connect is not in scope — this platform charges tenants a subscription fee, it does not pay out to them. |
| 1.8 | 04/08/2026 | Accepted ADR-016 (Production Events, implemented as `production_events`/`production_event_inputs`/`production_event_outputs`, replacing the bicycle-specific `repairs`/`repair_parts_used` tables) — the gate was met once a second and third vertical (cafe, pharmacy) began active scoping. Added ADR-022 (`inventory_lots` canonical lot/batch + expiry-date tracking) and ADR-023 (pharmacy `prescription_details` extension, deliberately excluding patient identity/clinical fields). Added PD-010 (supporting pharmacy as a third vertical; data-minimisation decision, not a full GDPR compliance sign-off — see Q-053). Removed the ADR-016 row from "Decisions Requiring Action" now that it's Accepted. |
| 1.9 | 08/08/2026 | Added BD-007: the additional-branch/location add-on subscription price, €30/month per branch, billed as its own fully separate Stripe subscription (not a quantity line item on the primary €80/month subscription) — implemented and live in Stripe test mode (`11_Development_Roadmap.md` v1.37). Added a BD-007 Consistency Status note mirroring BD-005's, stating the two prices are additive, not a combined tier. |
