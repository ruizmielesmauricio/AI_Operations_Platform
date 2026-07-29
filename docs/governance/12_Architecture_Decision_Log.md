# 12_Decision_Register.md

**Version:** 1.0
**Status:** Accepted
**Phase:** Company Governance
**Author:** Founder & CTO
**Last Updated:** 29/07/2026

---

# Document Contract

## Purpose

This is the **single canonical register** of all significant business, product, architecture, and engineering decisions.

It supersedes and merges two previously conflicting registers:

* `11_ADRs.md` (technical documentation set)
* `12_Architecture_Decision_Log.md` (governance documentation set)

Both prior registers used overlapping ID numbers for different decisions, and one contained a duplicate ID. All decisions from both have been preserved here under a single, non-conflicting numbering scheme, with prior IDs recorded for traceability.

**Both prior files should now be deleted or marked Superseded to prevent conflicting instructions existing in the repository** (per `06_Development_Rules.md`, "Do not leave conflicting instructions in different documents").

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
| BD-005 | **Set the working reference price at €80 per month per business** | **Accepted** | supersedes tech BD-001 (€79, Proposed) |
| BD-006 | Position the product as a complement to the customer's existing POS, not a replacement | Accepted | new |

---

# Product Decisions (PD)

| ID | Decision | Status | Prior ID |
|---|---|---|---|
| PD-001 | Start with bicycle shops but design for multiple business types | Accepted | tech PD-001 |
| PD-002 | Organise the platform around five operational domains (see reconciliation in `02_Operational_Domains.md`) | Accepted | gov PD-001 + tech PD-002 |
| PD-003 | Workshop/Production Operations is part of Version 1 | Accepted | gov PD-002 |
| PD-004 | Every feature must save time, save money, reduce operational risk, or improve decisions | Accepted | gov PD-003 |
| PD-005 | Begin with CSV and Excel uploads before building POS integrations | Accepted | tech PD-003 |

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
| ADR-011 | Use Stripe for subscription billing, supporting cards and SEPA Direct Debit | Accepted | tech ADR-011 + gov ADR-004(b) |
| ADR-012 | Use a shared database with tenant-scoped rows initially | Accepted | tech ADR-012 |
| ADR-013 | Use Neon for managed PostgreSQL and Supabase Auth for identity only (auth-only, not database or storage) | Accepted | gov ADR-004(a) |
| ADR-014 | Separate the platform into specialised engines: Database, Calculation, Machine Learning, AI | Accepted | gov ADR-003 |
| ADR-015 | Route AI requests through OpenRouter behind the internal AI Provider Gateway, selecting cost-effective, EU-compliant models above a defined quality threshold | **Proposed** | new |
| ADR-016 | Generalise repairs and recipes into a shared canonical "Production Events" entity rather than industry-specific tables | **Proposed** | new |
| ADR-017 | Use Cloudflare R2 (S3-compatible) for object storage | Accepted | from `08_Tech_Stack.md` |
| ADR-018 | Deploy via Docker containers to a low-cost VPS, with managed services for stateful components | Accepted | from `07_Deployment_Guide.md` |

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

---

# Decisions Requiring Action

| ID | Status | What's Needed to Move to Accepted |
|---|---|---|
| ADR-015 (OpenRouter) | Proposed | Define a numeric quality/reliability threshold and evaluation test set (`05_AI_Strategy.md`, Model Evaluation) |
| ADR-016 (Production Events) | Proposed | Validate the pattern against a third business type; update `04_Database.md` and `09_Product_Modules.md` |

---

# Downstream Updates Required by BD-005 (€80 Price)

The following files still reference **€79** and must be updated:

- [ ] `docs/technical/02_Business_Model.md` — "Initial Commercial Model" section
- [ ] `docs/technical/11_ADRs.md` — delete or mark Superseded (replaced by this file)
- [ ] `docs/governance/12_Architecture_Decision_Log.md` — delete or mark Superseded (replaced by this file)

Already using €80 correctly:

- [x] `docs/governance/08_Cost_Analysis.md`
- [x] `docs/governance/09_Business_Model.md`
- [x] Customer pitch one-pager
- [x] Internal founder one-pager

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
| 1.0 | 29/07/2026 | Merged `11_ADRs.md` and `12_Architecture_Decision_Log.md` into one canonical register; resolved duplicate ADR-004; set price to €80 (BD-005); added ADR-015 through ADR-018 and ED-005 through ED-008. |
