# 02_Operational_Domains.md

**Version:** 0.2 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** TBD

---

# Document Contract

## Purpose

This document defines the operational domains the platform analyses and acts on.

An operational domain is a coherent area of a small business's day-to-day operations that the platform observes, measures, explains, and recommends actions for. This document explains what each domain covers, what business questions it answers, what data it depends on, and how the domains relate to one another and to the platform's supporting layers (knowledge and AI).

It is the bridge between the Company Constitution (why we exist) and the technical module design in `10_Product_Requirements.md` (how each domain is calculated).

---

## Audience

* Founder
* Product Team
* Engineering Team
* Future Employees
* Investors

---

## In Scope

* Definition of each operational domain
* Business questions each domain answers
* Required and optional data per domain
* Relationship between domains
* Relationship between operational domains and supporting platform layers
* Reconciliation of domain terminology used elsewhere in this repository

---

## Out of Scope

This document intentionally does **not** define:

* Detailed metric formulas (see `10_Product_Requirements.md`)
* Database schema (see `06_Database_Design.md`)
* AI prompt design (see `05_AI_Architecture.md`)
* Pricing or packaging by domain (see `09_Business_Model.md`)
* UI/dashboard layout specifics (see `10_Product_Requirements.md`)

---

## Related Documents

* 00_Company_Constitution.md
* 01_Project_Vision.md
* 10_Product_Requirements.md (detailed set)
* 06_Database_Design.md
* 05_AI_Architecture.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

The platform organises everything it does around a small number of **operational domains** — the parts of a business that generate data, create decisions, and benefit from analysis.

There are three **analytical domains** that mirror how a bike shop owner actually thinks about their business — retail, workshop, and money — plus two **supporting domains** that make the analytical domains explainable and accessible: a knowledge layer and an AI decision-support layer.

This document also resolves a naming inconsistency between two earlier drafts in this repository (see "Reconciling Domain Terminology" below) so that all future documents use one consistent structure.

---

# Reconciling Domain Terminology

Two earlier documents describe "five domains" using different names. Both are correct in intent but were written at different levels of abstraction:

| Source | Domain List | Level of Abstraction |
|---|---|---|
| `12_Decision_Register.md` (PD-002) | Retail Operations, Workshop Operations, Financial Performance, Business Knowledge, AI Decision Support | Organisational / architectural grouping |
| `10_Product_Requirements.md` | Forecasting, Inventory Optimization, Profitability, Returns & Warranty, Repairs | Functional / analytical modules |

**Resolution adopted in this document:**

The PD-002 grouping is treated as the top-level operational structure, because it separates *what the business does* (Retail, Workshop, Financial Performance) from *how the platform supports it* (Business Knowledge, AI Decision Support). The `10_Product_Requirements.md` list is not a competing taxonomy — its five modules are analytical functions that live **inside** the three business-facing domains:

```text
Retail Operations
  ├── Inventory Optimization
  └── (Sales data feeds Profitability and Forecasting)

Workshop Operations
  └── Repairs

Financial Performance
  ├── Profitability
  ├── Forecasting
  └── Returns & Warranty
```

**Open decision:** Returns & Warranty currently spans both Retail and Financial Performance (a return affects stock and margin). This document assigns it to Financial Performance because its primary business question is margin/cost impact, but this should be revisited once pilot data shows where owners actually look for return information. See "Questions Still Open."

---

# The Five Domains

## 1. Retail Operations

**Definition:** Everything related to selling products — inventory, sales, suppliers, and stock health.

**Business questions answered:**

* What is selling quickly, and what is not moving?
* What might run out?
* What should be reordered, and how much?
* How much cash is tied up in stock that isn't turning over?

**Primary data required:** Sales transactions, product catalogue, stock levels, supplier information.

**Corresponds to:** Inventory Optimization module in `10_Product_Requirements.md`.

---

## 2. Workshop Operations

**Definition:** Everything related to service and repair work — job tracking, labour, parts usage, and turnaround.

**Business questions answered:**

* How much revenue does the workshop generate?
* How long do repairs take, and where are the delays?
* Which repair types are profitable?
* How productive is workshop capacity?

**Primary data required:** Repair/work-order records, status history, labour entries, parts used.

**Corresponds to:** Repairs module in `10_Product_Requirements.md`.

---

## 3. Financial Performance

**Definition:** The business's overall profitability, margin, and forward-looking outlook, including the cost impact of returns and warranty issues.

**Business questions answered:**

* Which products, services, or categories create profit?
* Why did profit or margin change?
* What revenue is likely next week or month, and how confident is that forecast?
* Which returns or warranty patterns are costing the business money?

**Primary data required:** Revenue and cost data, historical sales for forecasting, return/warranty records.

**Corresponds to:** Profitability, Forecasting, and Returns & Warranty modules in `10_Product_Requirements.md`.

---

## 4. Business Knowledge

**Definition:** A supporting domain, not an analytical one. It holds the reference information the platform needs to answer questions correctly and consistently — metric definitions, business-template rules, customer-specific policies, and (in later versions) retrievable documentation such as warranty terms or supplier agreements.

**Business questions answered:**

* What does this metric mean?
* What is our policy for this situation?
* What terminology does this business template use?

**Primary data required:** Metric definitions, business template configuration, approved documentation (future RAG use per `05_AI_Architecture.md`).

**Note:** This domain does not calculate business outcomes. It exists so the other domains and the AI layer have a consistent, approved source of definitions and policy to draw from.

---

## 5. AI Decision Support

**Definition:** A supporting domain that turns the deterministic output of the other domains into plain-language explanations, prioritized recommendations, and answers to natural-language questions.

**Business questions answered (on behalf of the other domains):**

* Why did this happen, in plain language?
* What should I do next, and why?
* What does this number mean for my business?

**Primary data required:** Structured findings and metrics produced by the other domains (never raw data, per `05_AI_Architecture.md`).

**Note:** Per the Company Constitution (Principle 3, "Business Logic First") and ADR-007, this domain never generates numbers. It explains numbers that Retail Operations, Workshop Operations, and Financial Performance have already calculated.

**The customer-facing conversational agent (PD-008, ADR-020):** Customers interact with this domain through a single chat interface, behaving similarly to a general AI assistant from the customer's point of view. Behind that one interface, every question is routed down one of three lanes by an intent classifier — never answered by free-form AI generation:

1. **Business-data Q&A** — "What were our sales yesterday?", "What are our most/least popular products?". The AI classifies the question against a fixed set of approved deterministic query functions (already computed by Retail/Workshop/Financial Performance), the matching function runs in code, and the AI phrases the returned numbers in plain language. The AI never computes the answer itself.
2. **Report explanation** — plain-language walkthroughs of the weekly/monthly reports defined in PR-8, answering "why" questions about a report the customer is already looking at.
3. **Product/support help** — "Why was my import rejected?", "How do I invite a teammate?". These are not business-data questions, so they are answered by retrieving from an approved help-content knowledge base (the Business Knowledge domain, above) rather than any calculation path. Where the knowledge base cannot resolve the question, the agent hands off to human support rather than guessing.

This resolves the "Should Business Knowledge remain purely internal, or become a customer-visible module?" question below in favour of the latter, scoped specifically to support/help content.

---

# Business Perspective

Owners do not think in terms of "modules" or "domains" — they think in terms of the parts of their shop: the counter, the workshop, and the bank balance. Structuring the platform around Retail, Workshop, and Financial Performance keeps the product aligned with how a bike shop owner already organises their mental model of the business, while Business Knowledge and AI Decision Support remain invisible scaffolding rather than customer-facing "modules."

---

# Customer Perspective

A customer should experience the platform as three connected views of their business (retail, workshop, money) that are explained in plain language and always traceable back to their own data — never as five abstract "domains."

---

# Technical Perspective

Each analytical domain (Retail Operations, Workshop Operations, Financial Performance) maps to one or more deterministic calculation modules described in `10_Product_Requirements.md`, each with its own metrics, rules, findings, and recommendations. Business Knowledge and AI Decision Support are cross-cutting platform services (per `03_System_Architecture.md`'s Analytics Engine and AI Provider Gateway) rather than domains with their own database entities and dashboards.

---

# Current Decisions

* The platform is organised around three customer-facing operational domains: Retail Operations, Workshop Operations, and Financial Performance.
* Business Knowledge and AI Decision Support are supporting domains, not customer-facing analytical modules.
* Returns & Warranty is provisionally assigned to Financial Performance (open to revision — see below).

---

# Why This Decision?

**Decision:** Use PD-002's grouping as the top-level domain structure, with `10_Product_Requirements.md`'s five modules nested inside it.

**Reason:** Avoids maintaining two conflicting "five domains" lists across the repository, and matches how an owner actually experiences their business.

**Alternatives Considered:** Keeping `10_Product_Requirements.md`'s five modules as the top-level structure and dropping Business Knowledge / AI Decision Support as named domains entirely. Rejected because those two layers are referenced elsewhere (README, AI Strategy) as first-class parts of the platform and deserve documentation, even if they aren't customer-facing dashboard sections.

**Future Review Criteria:** Revisit once pilot interviews (`15_Customer_Discovery.md`) show whether owners think of returns/warranty as a retail concern or a financial concern.

---

# Risks

* Reconciling two terminologies retroactively may cause confusion if older documents are read without this reconciliation section. Mitigation: this document is now the canonical reference; other documents should link here rather than restate domain lists.
* Treating Returns & Warranty as a sub-topic of Financial Performance rather than its own domain may under-emphasise it in early dashboard design. Mitigation: `10_Product_Requirements.md` still gives it a full module treatment with its own metrics and recommendations.

---

# Future Improvements

* As new business templates are added (garages, cafés, retailers), confirm whether "Retail Operations" and "Workshop Operations" still fit, or whether a more generic domain name (e.g., "Service Operations") is needed for non-repair service businesses.
* Consider whether Business Knowledge should become a customer-facing feature (e.g., a searchable help/policy assistant) rather than a purely internal supporting layer, per the README's "Warranty & Policy Assistant" and "Business Knowledge Base (RAG)" future features. **Decided (PD-008):** yes, scoped to product/support help content surfaced through the conversational agent's support lane.

---

# Questions Still Open

* Should Returns & Warranty be its own top-level domain once pilot data is available?
* Does "Retail Operations" and "Workshop Operations" naming generalise cleanly to non-bike-shop templates?
* What content populates the support-lane knowledge base at prototype stage, and who maintains it as the product changes?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial draft; reconciled domain terminology between PD-002 and 10_Product_Requirements.md. |
| 0.2 | 30/07/2026 | Added the customer-facing conversational agent design to AI Decision Support (PD-008, ADR-020): three intent-classified lanes (business-data Q&A, report explanation, product/support help), resolving the open question on whether Business Knowledge becomes customer-visible. |
