# 03_System_Architecture.md

**Version:** 0.2 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---

# Document Contract

## Purpose

This document defines the system architecture at the level a founder, investor, or new employee needs to understand how the platform is built and why — without needing to read implementation-level detail.

It summarises the architecture, states the governing principles behind key structural choices, and records the current thinking on AI provider routing, including the planned use of OpenRouter.

Deployment operations are governed by `07_Deployment_Guide.md`; database structure and product behaviour are governed by `06_Database_Design.md` and `10_Product_Requirements.md`.

---

## Audience

* Founder
* Engineering Team
* Future Employees
* Investors

---

## In Scope

* Architectural goals and principles
* High-level system structure
* Multi-tenancy approach
* AI provider routing strategy, including OpenRouter
* How architecture decisions map to the Company Constitution

---

## Out of Scope

This document intentionally does **not** define:

* Deployment and operational procedures (see `07_Deployment_Guide.md`)
* Database schema (see `06_Database_Design.md`)
* Deployment steps (see `07_Deployment_Guide.md`)
* Technology selection rationale by tool (see `04_Technology_Stack.md`)
* AI prompt design or cost controls (see `05_AI_Architecture.md`)

---

## Related Documents

* 00_Company_Constitution.md
* 02_Operational_Domains.md
* 05_AI_Architecture.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

The platform is a multi-tenant SaaS system with a Next.js front end, a FastAPI backend, PostgreSQL as the system of record, and a background worker for anything long-running.

Two architectural commitments matter more than any specific tool choice:

1. **Business Logic First** — calculations happen in deterministic application code, never in an AI model.
2. **AI-Agnostic** — no feature depends on one AI provider. The platform is planning to route AI requests through **OpenRouter**, which allows the platform to select among multiple underlying models based on cost, EU regulatory compliance, and a quality threshold — without hard-coding a single vendor's SDK into business modules.

Everything else in this document explains how those two commitments are implemented structurally.

---

# Architectural Goals

The platform must be:

* Multi-tenant
* Low cost
* Secure
* Portable
* Testable
* Modular
* Operable by one founder
* Able to scale gradually
* Independent of a single AI provider
* Independent of AWS-specific services
* Suitable for EU customer data

(Full detail: `03_System_Architecture.md`, "Architectural Goals")

---

# High-Level System Structure

```text
Public Website
      |
      v
Next.js Web Application
      |
      v
FastAPI Application API
      |
      +--------------------------+
      |                          |
      v                          v
PostgreSQL                  Background Jobs
      |                          |
      v                          v
Analytics and Rules         Imports / Forecasts /
Engine                      Notifications / Reports
      |
      v
Structured Insight Payloads
      |
      +--------------------------+
      |                          |
      v                          v
Browser Charts             AI Explanation Layer
      |                          |
      +------------+-------------+
                   |
                   v
              User Dashboard
```

Component-level responsibility (frontend, API, database, object storage, worker, Redis, billing, email, monitoring) is documented in `03_System_Architecture.md`.

---

# Multi-Tenancy

A shared PostgreSQL database with tenant-scoped rows is used initially, defended in depth through authentication, membership lookup, application authorization, query scoping, and (where supported) Row Level Security.

(Full detail: `03_System_Architecture.md`, "Multi-Tenant Architecture")

---

# AI Provider Routing Strategy

## Governing Principle

Per the Company Constitution (Principle 6, AI-Agnostic Architecture) and ADR-006 / ED-006, no business module may call an AI provider's SDK directly. All AI requests pass through a single internal **AI Provider Gateway** (`05_AI_Architecture.md`), which is responsible for provider selection, prompt construction, output validation, and cost tracking.

## Planned Use of OpenRouter (Summary)

The platform plans to route AI requests through **OpenRouter**, as one implementation behind the internal `AIProvider` interface — not a new dependency inside business modules:

```text
Business Modules -> AI Provider Gateway -> (OpenRouter or direct provider) -> Model
```

This is an architecture-layering decision: the specific routing service can be swapped later without touching Retail Operations, Workshop Operations, or Financial Performance modules. It does not change the Business Logic First rule — AI still only explains calculated output.

**Full reasoning, selection criteria, and status:** see `05_AI_Architecture.md`, "Provider Independence and OpenRouter" (canonical). This document does not restate it.

**Status:** Proposed — pending a dedicated ADR once cost and quality thresholds are tested with pilot usage.

---

# Business Perspective

The founder is one person. A single AI gateway with provider routing (rather than direct integrations with multiple vendors) keeps AI cost and reliability manageable without needing a team dedicated to model evaluation.

---

# Customer Perspective

Customers should never notice which model answered their question — only that the explanation is accurate, fast, and grounded in their own data. Provider routing is invisible infrastructure, not a customer-facing feature.

---

# Technical Perspective

The AI Provider Gateway remains the only place a provider SDK (or router SDK, such as OpenRouter's) is referenced in the codebase. This preserves the layering described in `03_System_Architecture.md`:

```text
Business Modules -> AI Provider Gateway -> (OpenRouter or direct provider) -> Model
```

---

# Commercial Perspective

Provider routing directly supports the Cost Strategy goal of keeping "AI as a small portion of the cost per customer" (`09_Business_Model.md`, `08_Cost_Analysis.md`) by allowing continuous cost optimisation without re-engineering the product every time model pricing changes.

---

# Current Decisions

* The platform uses a single internal AI Provider Gateway; no business module calls a provider SDK directly (Accepted — ADR-006, ED-006).
* The platform plans to route AI requests through OpenRouter to select cost-effective, EU-compliant models above a quality threshold (Proposed — pending ADR).

---

# Why This Decision?

**Decision:** Route AI requests through OpenRouter as an implementation detail behind the existing AI Provider Gateway.

**Reason:** Preserves AI-agnosticism while giving the company a practical way to control cost and enforce a quality/compliance floor, without building and maintaining direct integrations with every individual model vendor.

**Alternatives Considered:** Direct integration with a single provider (rejected — creates vendor lock-in and removes cost flexibility); building a custom routing layer in-house (rejected for now — not justified before pilot-stage usage volume).

**Future Review Criteria:** Revisit once real usage data shows actual cost-per-question, hallucination rate, and latency across candidate models, and once a specific quality threshold can be defined numerically rather than qualitatively.

---

# Risks

* Relying on a third-party router introduces a dependency; mitigation is that the router sits behind the internal interface and can be replaced.
* "Cheapest model that meets a quality threshold" requires the threshold to be defined and tested, or cost optimisation could quietly degrade explanation quality. Mitigation: this must be paired with the output validation rules already defined in `05_AI_Architecture.md` before OpenRouter routing is enabled in production.

---

# Future Improvements

* Define the specific quality threshold and evaluation test set referenced in `05_AI_Architecture.md`'s "Model Evaluation" section, then formalise OpenRouter as an ADR.
* Track per-model cost and hallucination-rate metrics once pilot usage begins, to validate the routing strategy with evidence.

---

# Scheduled Performance Reporting Architecture

The platform generates two independent report types through deterministic background jobs:

* **Weekly:** every Monday at 08:00 in the customer's configured timezone, covering the previous completed week.
* **Monthly:** on the first calendar day at 08:00 in the customer's configured timezone, covering the previous completed month.
* If both schedules fall on the same day, both jobs run and create separate reports and notifications.

The worker obtains tenant-scoped data from Neon, calculates report figures and comparisons through backend code, renders the standard in-app report template, and creates an in-app notification. Scheduled reporting does not call the AI gateway and does not automatically create a file.

Each report is uniquely keyed by tenant, report type, and reporting period. This makes generation idempotent and prevents retries from creating duplicates. A primary scheduled job retries transient failures; an independent recovery job detects a missing report and forces regeneration. Persistent failure creates an internal operational alert.

The in-app report remains available for seven days. Its notification states the expiry date. After expiry, the customer-facing report payload may be removed, while a minimal audit record remains in Neon containing report identity, reporting period, status, attempts, timestamps, notification status, and failure reason. PDF or Word is generated only when the customer requests an export through the SaaS.

Accepted reporting behaviour is governed by PD-007 and ADR-019 in `12_Decision_Register.md`.

---

# Questions Still Open

* What is the minimum acceptable quality threshold, and how is it measured before launch?
* Which EU regulatory requirements specifically constrain model selection, and how are they encoded into the routing rules?
* Should there be a manual override to force a specific model for certain customers or use cases (e.g., enterprise pilot customers with stricter requirements)?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial draft; documented planned use of OpenRouter for AI provider routing. |
| 0.2 | 30/07/2026 | Trimmed the "AI Provider Routing Strategy" section to a summary + pointer to `05_AI_Architecture.md` (removed ~30 lines duplicating that document almost verbatim, consistent with this document's own Out of Scope declaration); fixed stale `01_Product_Vision.md` filename references; removed the self-referential "(detailed set)" Related Document. |
