# 04_Technology_Stack.md

**Version:** 0.3 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---

# Document Contract

## Purpose

This document records, at a governance level, what technology the company has chosen and why each choice serves the Company Constitution — specifically the principles of low operating cost, portability, and avoiding vendor lock-in.

It records the selected technology categories and explains why they serve the platform's governance principles. Implementation and deployment procedures are maintained in `07_Deployment_Guide.md`.

---

## Audience

* Founder
* Engineering Team
* Future Employees
* Investors

---

## In Scope

* The technology stack at a category level (frontend, backend, database, AI, storage, billing, hosting)
* The reasoning behind each category choice
* Vendor lock-in and portability considerations
* How the stack serves the Company Constitution

---

## Out of Scope

This document intentionally does **not** define:

* Library versions, configuration, or code-level detail (implementation documentation)
* Deployment steps (see `07_Deployment_Guide.md`)
* Database schema (see `06_Database_Design.md`)
* AI provider routing detail (see `05_AI_Architecture.md`)

---

## Related Documents

* 00_Company_Constitution.md
* 03_System_Architecture.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

The stack is chosen to be boring, replaceable, and cheap — not impressive. Every category (frontend, backend, database, storage, billing, AI) uses a widely supported, portable technology rather than a proprietary or single-vendor service, so the company is never forced to rebuild the product to change a vendor.

| Category | Choice | Portability Note |
|---|---|---|
| Frontend | Next.js, React, TypeScript | Standard framework, no proprietary hosting requirement |
| Backend | FastAPI, Python | Runs on any container host |
| Database | PostgreSQL hosted on Neon | Standard SQL, exportable, and independent from the authentication provider |
| Auth | Supabase Auth (auth-only) | Decoupled from the database provider (ADR-013) |
| Object Storage | Cloudflare R2 | Temporary uploaded files and generated file objects; S3-compatible and replaceable |
| Billing | Stripe | Industry standard; webhook-driven, not deeply coupled to app logic |
| AI | Internal gateway, routed via OpenRouter | AI-agnostic by design (see `05_AI_Architecture.md`) |
| Hosting | Low-cost VPS or managed container host | No AWS-specific services |

---

# Reasoning by Category

## Frontend — Next.js, React, TypeScript

Chosen for its maturity, large talent pool, and ability to serve both the public marketing site and the authenticated application from one project. TypeScript reduces defects in a small team with no dedicated QA function.

## Backend — FastAPI, Python

Chosen because Python has the strongest ecosystem for the data, analytics, and forecasting work central to the product (pandas, NumPy, scikit-learn, statsmodels). FastAPI's typed validation and async support keep the API layer maintainable for a solo founder.

## Database — PostgreSQL

Chosen as the single system of record because it is mature, portable, supports Row Level Security, and avoids the cost and complexity of a data warehouse before one is justified. Per ADR-013, PostgreSQL hosting (Neon) is deliberately decoupled from authentication (Supabase Auth), so no single vendor holds both the data and the identity layer.

## Authentication — Supabase Auth

Chosen for user signup, login, password resets, and session management. Supabase is used for identity only; Supabase Database and Supabase Storage are not part of the accepted architecture.

## Object Storage — Cloudflare R2

Chosen for temporary uploaded files and other file objects, not structured application data. Its S3-compatible API and low egress cost keep it portable; any other S3-compatible provider can replace it without an application rewrite. The PostgreSQL database remains in Neon.

## Billing — Stripe

Chosen for its maturity and support for both card and SEPA Direct Debit, giving EU customers payment method choice at checkout (ADR-011).

## AI — Internal Gateway, Routed via OpenRouter

Chosen so the product depends on an internal interface, not a specific model vendor. See `05_AI_Architecture.md` for the full reasoning, including the planned use of OpenRouter for cost- and compliance-aware model selection.

## Hosting — Low-Cost VPS / Managed Container Host

Chosen to keep fixed costs minimal at the prototype and pilot stages, explicitly avoiding AWS-specific managed services (ADR-009) and Kubernetes until scale justifies the added complexity.

---

# Business Perspective

Every category choice reduces two things a solo founder cannot afford: high fixed monthly cost, and the risk of being unable to switch a vendor if pricing or terms change.

---

# Customer Perspective

Customers never see the stack directly, but they benefit from it: EU-capable hosting options, standard security practices, and a company that can react quickly to vendor pricing or reliability problems without an emergency rebuild.

---

# Technical Perspective

No business module should import a vendor SDK directly except at the narrow boundary layers already defined in `03_System_Architecture.md` (repositories for the database, the AI Provider Gateway for AI, a payment service module for Stripe). This is what keeps the categories above genuinely replaceable rather than replaceable in theory only.

---

# Commercial Perspective

A low fixed-cost, vendor-flexible stack directly supports the unit economics goals in `08_Cost_Analysis.md` and keeps gross margin defensible at low customer counts.

---

# Current Decisions

* Use Next.js/React/TypeScript for the frontend (Accepted — ADR-004 in `12_Decision_Register.md`).
* Use FastAPI/Python for the backend (Accepted — ADR-005).
* Use PostgreSQL, with Neon for hosting and Supabase for auth only (Accepted — ADR-013 in `12_Decision_Register.md`).
* Use Cloudflare R2 for object/file storage; it does not store the PostgreSQL database (Accepted — ADR-017).
* Use Stripe for billing, supporting cards and SEPA Direct Debit (Accepted).
* Avoid AWS-specific services and Kubernetes until scale justifies them (Accepted — ADR-009).

---

# Why This Decision?

**Decision:** Choose portable, standard technologies over proprietary or all-in-one platforms in every category.

**Reason:** A one-person engineering team cannot absorb the cost of a forced migration; portability is a form of risk management, not just a technical preference.

**Alternatives Considered:** An all-in-one platform (e.g., a single vendor providing database, auth, storage, and functions together) was considered for speed of initial development, but rejected because it increases lock-in risk exactly where the Company Constitution says to avoid it.

**Future Review Criteria:** Revisit any category if a vendor's pricing, reliability, or terms change materially, or if usage scale genuinely requires a more specialised service (per the Scaling Path in `03_System_Architecture.md`).

---

# Risks

* Assembling several best-of-breed services (rather than one platform) increases integration surface area. Mitigation: keep every vendor behind a narrow internal boundary (repository, gateway, or adapter) as already required by `12_Decision_Register.md`.
* Some categories (Neon, Supabase, R2) are still relatively young companies compared to hyperscalers. Mitigation: standard, portable APIs (SQL, S3) mean migration is possible if needed.

---

# Future Improvements

* Formalise the outstanding stack ADRs (background job library, monitoring stack) once Phase 2 prototype work makes a specific choice necessary.
* Add a lightweight "vendor risk review" step to the Cost Decision Rule in `08_Cost_Analysis.md` so vendor concentration is checked, not just cost.

---

# Questions Still Open

* Which background job library (Celery, Dramatiq, RQ, or database-backed) will be formally selected, and when?
* Which monitoring stack will be adopted once the pilot phase begins?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial governance-level technology-stack draft. |
| 0.2 | 30/07/2026 | Clarified Neon as the sole PostgreSQL host, Supabase as authentication only, and Cloudflare R2 as object/file storage rather than a database. |
| 0.3 | 30/07/2026 | Removed a duplicate self-citation in Out of Scope and the self-referential "(detailed set)" Related Document. |
