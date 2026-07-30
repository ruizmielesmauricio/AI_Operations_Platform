# 05_AI_Architecture.md

**Version:** 0.3 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---

# Document Contract

## Purpose

This document explains, at a governance level, how Artificial Intelligence fits into the platform's architecture: what it is allowed to do, what it is never allowed to do, and how the company plans to control its cost and reliability — including the planned use of OpenRouter for model selection.

This document governs AI boundaries and architecture. Implementation-level prompt schemas, caching rules, and model evaluations must remain consistent with these rules and be documented during development.

---

## Audience

* Founder
* Engineering Team
* Future Employees
* Investors

---

## In Scope

* The role of AI within the architecture
* The boundary between calculation and explanation
* Provider independence and the planned use of OpenRouter
* Cost and quality control principles at a governance level

---

## Out of Scope

This document intentionally does **not** define:

* Prompt templates or structured JSON schemas (implementation documentation)
* Token/cost limits by plan (see `08_Cost_Analysis.md` and implementation documentation)
* Caching implementation (implementation documentation)
* Database schema for AI usage tracking (see `06_Database_Design.md`)

---

## Related Documents

* 00_Company_Constitution.md
* 03_System_Architecture.md
* 08_Cost_Analysis.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

AI in this platform has exactly one job: **explain what deterministic code has already calculated.** It never calculates, aggregates, validates, or invents a number itself.

All AI requests pass through a single internal gateway. The company plans to route those requests through **OpenRouter**, which lets the gateway pick the cheapest model that still clears an approved quality and EU-compliance bar for each type of request — so cost control and hallucination control are handled by the same routing decision, not treated as separate concerns.

---

# The Core Rule

> AI explains. Application code calculates.

This is ADR-007 in `12_Decision_Register.md` and the Core Rule in `05_AI_Architecture.md`. Every other decision in this document exists to protect that rule.

---

# What AI May Do

* Executive summaries and plain-language explanations
* Suggested actions, worded from approved findings
* Answering natural-language questions about the business
* Explaining anomalies and forecasts
* Classifying user intent and selecting relevant approved metrics

(Full list: `05_AI_Architecture.md`, "AI Responsibilities")

# What AI Must Never Do

* Calculate revenue, profit, margin, or any other KPI
* Aggregate transactions or clean/validate data
* Produce chart values
* Authorize access or update billing state
* Invent a missing figure

(Full list: `05_AI_Architecture.md`, "AI Prohibitions")

---

# Provider Independence and OpenRouter

## Why Provider Independence Matters

Per the Company Constitution (Principle 6) and ADR-006/ED-006, no business feature may depend on a single AI vendor. This protects the company from price increases, capability changes, or availability problems with any one provider, and keeps the door open to better or cheaper models as they emerge.

## Planned Architecture

```text
Business Modules
      |
      v
Internal AIProvider Interface   <-- the only interface business code depends on
      |
      v
AI Provider Gateway
      |
      v
OpenRouter (planned)
      |
      v
Underlying model (selected per request)
```

The internal `AIProvider` interface defined in `05_AI_Architecture.md` does not change. OpenRouter becomes the mechanism the gateway uses to reach a model — it is an implementation detail behind the interface, not a new dependency inside business modules.

## What OpenRouter Is Expected to Provide

* **Cost control** — routing to the cheapest available model that still meets the platform's quality bar, rather than committing to one provider's pricing regardless of task.
* **EU regulatory fit** — the ability to prefer or restrict model selection to providers/models that meet applicable EU data-processing and regulatory requirements.
* **A quality floor** — routing decisions must be constrained by a minimum reliability/quality threshold, so cost optimisation cannot silently increase hallucination risk. This directly protects the "Never Hallucinate Numbers" principle in `01_Project_Vision.md`, since even explanatory text must stay factually grounded in the structured data it was given.
* **Fallback behaviour** — if a selected model fails or times out, the gateway can fall back to an alternative model without the customer-facing feature needing to know.

## What Does Not Change

* Output validation (schema, maximum length, referenced metric codes, unsupported numeric claims) still applies uniformly, regardless of which model answered the request.
* Usage and cost logging (provider, model, tokens, cost, feature, business, user, timestamp, success/failure) still applies per request.
* The AI Prohibitions list above is unaffected by which model or router is used — no model, however cheap or capable, is permitted to calculate a number that belongs to deterministic code.

**Status:** Proposed. This becomes an Accepted ADR once a specific quality threshold and evaluation test set (per `05_AI_Architecture.md`, "Model Evaluation") have been defined and tested against candidate models.

---

# Business Perspective

AI cost is a variable cost per customer, and an unpredictable one if left unmanaged. Routing through OpenRouter is the mechanism by which the company intends to keep that cost "a small portion of the cost per customer," as required by `09_Business_Model.md`.

---

# Customer Perspective

Customers should experience consistent, trustworthy explanations regardless of which underlying model produced them. The routing strategy is invisible to them — what they should notice is that explanations are accurate, fast, and never contradict the numbers on their dashboard.

---

# Technical Perspective

The AI Provider Gateway remains the single place in the codebase where a provider or router SDK is referenced. Everything upstream of it (business modules, dashboards, recommendation engine) depends only on the internal `AIProvider` interface, exactly as described in `03_System_Architecture.md`.

---

# Commercial Perspective

A cost- and compliance-aware routing strategy supports the "AI-Agnostic" and "Action-Oriented Analytics" product principles in `01_Project_Vision.md` without requiring the company to negotiate or maintain relationships with multiple AI vendors directly.

---

# Current Decisions

* AI explains; it never calculates (Accepted — ADR-007).
* All AI requests pass through one internal gateway; no business module calls a provider SDK directly (Accepted — ADR-006, ED-006).
* The platform plans to route AI requests through OpenRouter for cost, compliance, and quality-threshold-aware model selection (Proposed — pending ADR and defined quality threshold).

---

# Why This Decision?

**Decision:** Adopt OpenRouter as the routing layer inside the existing AI Provider Gateway, rather than integrating one model vendor directly or building a custom router.

**Reason:** Gives the company a practical, low-effort way to keep AI costs low and enforce an EU-compliance and quality floor simultaneously, without diverging from the AI-agnostic architecture already committed to.

**Alternatives Considered:** Direct single-vendor integration (rejected — reintroduces the lock-in the architecture is designed to avoid); an in-house router (rejected for now — not justified at current scale, and duplicates a problem OpenRouter already solves).

**Future Review Criteria:** Revisit once pilot usage produces real data on cost-per-question, hallucination/error rate by model, and latency, and once a numeric quality threshold has been defined and tested.

---

# Risks

* A cost-first routing strategy could degrade explanation quality if the quality threshold is not enforced strictly. Mitigation: pair routing with the output validation rules in `05_AI_Architecture.md` before enabling cost-optimised routing in production.
* Introducing a third-party router adds one more vendor dependency. Mitigation: it sits behind the internal interface and is replaceable without touching business modules, consistent with the rest of the stack (`04_Technology_Stack.md`).

---

# Future Improvements

* Define and publish the numeric quality/reliability threshold referenced in `05_AI_Architecture.md`'s Model Evaluation section.
* Build a small internal dashboard (for the founder, not customers) tracking cost-per-question and error rate by model, to make the routing decision auditable over time.
* Formalise this document's "Proposed" OpenRouter decision as an Accepted ADR once the above is in place.

---

# Questions Still Open

* What is the minimum acceptable quality/reliability threshold, and how will it be measured before launch?
* Which specific EU regulatory requirements should be encoded as hard constraints on model selection, versus soft preferences?
* Should certain customers or plans be able to request a specific model tier, overriding the default cost-optimised routing?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial governance-level draft; recorded planned use of OpenRouter for AI provider routing. |
| 0.2 | 30/07/2026 | Fixed stale `01_Product_Vision.md` filename references (now `01_Project_Vision.md`); removed the self-referential "(detailed set)" Related Document. This document remains the canonical source for AI provider routing detail. |
| 0.3 | 30/07/2026 | Fixed a duplicate self-citation in the Technical Perspective section (`03_System_Architecture.md` was cited twice in the same sentence). |
