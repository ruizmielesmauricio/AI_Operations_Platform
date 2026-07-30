# 10_Product_Requirements.md

**Version:** 0.1 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 29/07/2026

---

# Document Contract

## Purpose

This document defines what the product must do, from the customer's point of view, at a governance level. It states the functional requirements, the non-functional requirements, and the acceptance criteria that determine whether a requirement has actually been met.

It contains one significant product decision that **supersedes earlier documentation**: the platform will not require customers to fill in an import template. See "Data Ingestion" below.

---

## Audience

* Founder
* Product Team
* Engineering Team
* Future Employees

---

## In Scope

* Functional requirements by module
* Data ingestion requirements (including the no-template decision)
* Non-functional requirements
* Acceptance criteria
* Explicit non-requirements

---

## Out of Scope

This document intentionally does **not** define:

* Metric formulas (see `10_Product_Requirements.md`)
* Database schema (see `06_Database_Design.md`, `06_Database_Design.md`)
* Architecture (see `03_System_Architecture.md`)
* Delivery sequencing (see `11_Development_Roadmap.md`)

---

## Related Documents

* 00_Company_Constitution.md
* 02_Operational_Domains.md
* 05_AI_Architecture.md
* 06_Database_Design.md
* 11_Development_Roadmap.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

The product must let a small business owner get from "I have a messy export from my POS" to "I understand what's happening in my business" with as little effort on their part as possible.

The single most important requirement in this document is that **the customer must not be asked to reformat their data.** They export whatever their system gives them, upload it, and the platform does the work of understanding it. This is a deliberate reversal of the earlier "downloadable import template" approach, and it moves significant complexity from the customer to our backend — which is exactly where it belongs.

---

# Core Product Requirements

## PR-1 — Onboarding

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| PR-1.1 | User can create an account and a business | Account created, business record exists, user is owner |
| PR-1.2 | User selects their business type | Business template activated; terminology adapts throughout the UI |
| PR-1.3 | Activate only operational modules applicable to the selected business type | Inapplicable modules, metrics, recommendations, and report sections are not shown |
| PR-1.4 | Reuse the common product and calculation core across business types | Selecting a template changes configuration, mappings, thresholds, extensions, and labels—not the application or canonical formulas |
| PR-1.3 | Onboarding asks a small number of operational questions | No more than 6 questions before first upload |
| PR-1.4 | User reaches first upload within 5 minutes of signup | Measured from account creation to upload screen |
| PR-1.5 | User invites additional users with roles | Invitation email sent; role-based permissions enforced server-side |

# Business-Type Configuration

The bicycle-shop template is the first implementation and validation target. Terms such as workshop, repair, bicycle, part, and mechanic are template labels or examples, not universal product entities.

Each validated template defines customer-facing terminology, enabled modules and report sections, canonical mappings, thresholds and rules, and governed extension attributes. Templates must not duplicate the application, create a separate database per industry, redefine a canonical metric inconsistently, or display an inapplicable module.

---

## PR-2 — Data Ingestion (Critical Section)

### The Requirement, Stated Plainly

**The customer will not be given a template to fill in.**

They export whatever their POS, accounting system, or spreadsheet produces, and upload it as-is. The platform is responsible for understanding it.

### Why This Changed

Earlier documentation (`01_Product_Vision.md`, "Low-Friction Use") proposed providing a downloadable import template. That approach has three problems that make it unworkable in practice:

1. **It assumes the customer has time.** A shop owner will not restructure a spreadsheet to match our column names. They will close the tab.
2. **It assumes the customer has the skill.** Column mapping is a data task. Our target user explicitly does not want to do data tasks (`01_Project_Vision.md`, Target User).
3. **It does not scale across industries.** A template per business type means maintaining templates for bike shops, garages, cafés, pet shops, florists — a growing maintenance burden that fights the Industry-Flexible Core principle.

If the customer has to do the data preparation, we have not removed the work — we have just moved it to the person least equipped to do it. The platform's value proposition is doing that work for them.

**This supersedes the "Provide a downloadable import template" line in `01_Product_Vision.md`, which should be updated.** Recorded as PD-006 in `12_Decision_Register.md`.

### Ingestion Requirements

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| PR-2.1 | Accept CSV, XLS, and XLSX in any column order | File parses regardless of column sequence |
| PR-2.2 | Detect the header row automatically, including when preceded by title rows, blank rows, or report metadata | Header correctly identified in files with up to 10 junk rows above it |
| PR-2.3 | Recognise common column names and aliases automatically | Known aliases (e.g. "Item", "Product", "Description", "Product Name", "SKU Description") map to the canonical field without user input |
| PR-2.4 | Where a column cannot be confidently matched, ask the user to confirm — in plain language, showing sample values | User sees "Which column is the sale date?" with three example values, not a technical schema mapping UI |
| PR-2.5 | Save the confirmed mapping and reuse it for all future uploads from that source | Second upload from the same source requires zero mapping input |
| PR-2.6 | Detect and normalise inconsistent formats without asking | Dates (DD/MM/YY, MM-DD-YYYY, ISO), currency symbols, thousand separators, decimal commas, trailing whitespace, mixed case |
| PR-2.7 | Handle messy real-world data gracefully | Blank rows, merged cells, subtotal rows, footer rows, duplicate headers mid-file, and trailing notes are detected and excluded |
| PR-2.8 | Explain every rejected row in plain language | "14 rows skipped: no date found" — never a stack trace or error code shown to the user |
| PR-2.9 | Never silently discard data | Every excluded row is counted, categorised, and visible in the import summary |
| PR-2.10 | Delete the uploaded file after successful ingestion | File removed from object storage; only normalised data retained (ADR-008) |
| PR-2.11 | Allow the user to undo an import | Import can be reversed transactionally, restoring prior state |

### The AI Boundary in Ingestion — Important

There is a real tension here that must be handled carefully.

`05_AI_Architecture.md` explicitly **prohibits** AI from validating files, cleaning data, and deduplicating records. Those prohibitions stand and are not weakened by this section.

However, `05_AI_Architecture.md` **permits** AI to classify intent and select from approved options. Suggesting which source column probably corresponds to which canonical field is a classification task, not a calculation.

The line the platform must hold:

| Task | Allowed? | Why |
|---|---|---|
| AI **suggests** that "Txn Dt" probably means `sale_date` | **Yes** | Classification against a fixed set of canonical fields |
| User or saved profile **confirms** that mapping | Required | The mapping becomes deterministic configuration |
| Deterministic code **applies** the mapping and transforms every row | **Yes — always code** | This is data transformation, not classification |
| AI reads the data values and "cleans" them | **No** | Prohibited. Cleaning is deterministic transformation |
| AI decides whether a row is a duplicate | **No** | Prohibited. Duplicate detection is deterministic |
| AI infers a missing value | **No** | Prohibited absolutely. This is inventing data |

**Rule of thumb:** AI may help decide *what a column means, once*. Code does *everything that touches the actual data*. A mapping suggestion is reviewed and stored; it is not re-derived per row, per upload, or per customer.

This should be recorded as an engineering constraint and tested — see PR-6.4.

## PR-3 — Analytics and Dashboards

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| PR-3.1 | Calculate all metrics deterministically from stored data | Same input always produces same output; covered by unit tests |
| PR-3.2 | Display current status, trend, drivers, risks, and recommended action per module | Every module section contains all five elements |
| PR-3.3 | Render charts in the browser from structured API payloads | No server-rendered chart images in normal dashboard use (ADR-010) |
| PR-3.4 | Allow drill-down from any metric to underlying records | User can reach the source rows behind any number |
| PR-3.5 | Show data completeness and confidence alongside metrics | Metrics based on partial data are visibly flagged |
| PR-3.6 | Distinguish revenue analysis from profit analysis when cost data is absent | Product does not imply profit figures it cannot support |
| PR-3.7 | Display metric definitions on demand | Every metric has an accessible plain-language definition |

## PR-4 — Findings and Recommendations

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| PR-4.1 | Generate findings deterministically from rules | Findings reproducible; rule version recorded |
| PR-4.2 | Map findings to recommendations from an approved action library | No recommendation exists without a source finding |
| PR-4.3 | Prioritise recommendations by impact | Ranked list, not undifferentiated |
| PR-4.4 | Show evidence behind every recommendation | User can see the metric values that triggered it |

## PR-5 — AI Explanation

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| PR-5.1 | Explain calculated findings in plain language | Explanations reference only supplied structured context |
| PR-5.2 | Answer natural-language questions about the business | Answers grounded in calculated metrics, never invented |
| PR-5.3 | Reject or flag any AI numeric claim not present in structured input | Output validation blocks unsupported figures |
| PR-5.4 | Degrade gracefully when AI is unavailable | Dashboards and metrics remain fully functional; clear message shown |
| PR-5.5 | Enforce per-tenant AI usage limits | Limits applied server-side; usage logged per request |

## PR-6 — Security and Tenancy

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| PR-6.1 | Enforce tenant isolation on every request | Integration tests prove cross-tenant access fails |
| PR-6.2 | Never trust a `business_id` supplied by the browser | Membership verified server-side on every tenant-owned resource |
| PR-6.3 | Enforce role-based permissions server-side | UI state never grants authorisation |
| PR-6.4 | Prevent AI from performing calculation or data transformation | Automated test asserts no data-transformation path routes through `backend/app/ai/` |
| PR-6.5 | Audit privileged actions | Audit event recorded for permission, billing, and deletion actions |

## PR-7 — Billing

| ID | Requirement | Acceptance Criteria |
|---|---|---|
| PR-7.1 | Subscribe via Stripe Checkout | Card and SEPA Direct Debit both offered |
| PR-7.2 | Update access only from verified webhooks | Browser redirect alone never grants paid access |
| PR-7.3 | Manage billing via Stripe Customer Portal | User can update payment method and cancel |

---

# Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Dashboard load time | Under 2 seconds for a typical business |
| NFR-2 | Import processing | 10,000 rows processed within 60 seconds |
| NFR-3 | Availability | 99% during pilot; higher post-launch |
| NFR-4 | Data residency | EU region |
| NFR-5 | Uploaded file retention | Deleted after successful import by default |
| NFR-6 | AI cost per customer | Under EUR 3/month average |
| NFR-7 | Accessibility | Charts have text alternatives; keyboard navigable |
| NFR-8 | Mobile | Dashboards readable on phone; full editing desktop-first |

---

# Explicit Non-Requirements

The product will **not**, in the initial version:

* Process payments or act as a POS
* Replace accounting software or file tax returns
* Provide regulated financial or legal advice
* Offer real-time POS integrations (deferred; PD-005)
* Support multi-location comparison (deferred)
* Provide a public API (deferred)
* Require customers to format their data to our specification

---

# Business Perspective

The no-template decision is the difference between a product an owner tries once and abandons, and one they use monthly. Every hour of engineering spent on schema detection buys back an hour of customer effort — and customer effort is the thing that kills adoption.

---

# Customer Perspective

The customer's mental model should be: *"I sent them my sales export and it just worked."* Anything more complicated than that is a failure of this document.

---

# Technical Perspective

Schema-agnostic ingestion is genuinely hard, and this document should not pretend otherwise. The realistic approach is layered: alias dictionaries first (cheap, deterministic, covers most cases), then structural heuristics, then a one-time AI-assisted suggestion for the residual, then saved mapping profiles so the cost is paid once per source rather than once per upload.

---

# Commercial Perspective

Removing the template requirement removes the single largest onboarding drop-off risk, and directly supports the "Time to first value" metric in `11_Development_Roadmap.md`'s Phase 4 validation.

---

# Current Decisions

* No customer-facing import template; the platform performs schema detection and normalisation (**PD-006, Accepted** — supersedes `01_Product_Vision.md` onboarding guidance)
* Business templates configure terminology and applicability on the shared core; they do not create separate products or databases (**PD-008 and ADR-020, Accepted**)
* AI may suggest column mappings once, but never transforms, cleans, validates, or deduplicates data (**ED-009, Accepted**)
* Uploaded files deleted after successful ingestion (ADR-008, Accepted)

---

# Why This Decision?

**Decision:** Remove the customer-facing import template and place schema detection responsibility on the backend.

**Reason:** The target user has neither the time nor the inclination to prepare data. A template shifts work to the customer, which contradicts the product's core value proposition and creates a per-industry maintenance burden that fights the Industry-Flexible Core principle.

**Alternatives Considered:** Providing templates per business type (rejected — does not scale, and customers won't use them). Requiring a POS integration instead of uploads (rejected — premature before validation, per PD-005). Offering templates as *optional* for customers who want them (partially retained — a template may be offered as a fallback, but never required).

**Future Review Criteria:** Revisit if pilot data shows automatic detection succeeds on fewer than ~80% of real customer files without manual confirmation.

---

# Risks

* Schema detection may prove harder than estimated against real-world POS exports; mitigation is the layered approach plus saved mapping profiles, and honest plain-language fallback to user confirmation.
* The AI-suggestion boundary could erode over time under delivery pressure ("just let the model clean it"). Mitigation: PR-6.4 makes this a tested constraint, not a convention.
* Customers may upload data containing personal information we do not need. Mitigation: data minimisation at ingestion; do not import fields the template does not require.

---

# Future Improvements

* Build a library of known POS export formats (Lightspeed, Shopify, Square, common Irish EPOS providers) so those are recognised instantly with zero user input.
* Add a confidence indicator to auto-detected mappings so users can spot-check rather than confirm everything.
* Measure detection success rate as a product metric from the first pilot.

---

# PR-4 — Scheduled Performance Reports

## PR-4.1 Scheduling and period

| ID | Requirement | Acceptance criterion |
|---|---|---|
| PR-4.1 | Generate a weekly report every Monday at 08:00 in the customer's configured timezone | Report covers the previous completed week |
| PR-4.2 | Generate a monthly report on the first calendar day at 08:00 in the customer's configured timezone | Report covers the previous completed calendar month |
| PR-4.3 | Keep weekly and monthly reports separate when schedules coincide | Two reports and two notifications are created |

## PR-4.2 Delivery, access and exports

| ID | Requirement | Acceptance criterion |
|---|---|---|
| PR-4.4 | Deliver each report as an in-app report with its own notification | No automatic email attachment or report file is created |
| PR-4.5 | Keep the customer-facing report available for seven days | Notification displays the report's exact expiry date |
| PR-4.6 | Offer PDF or Word only as an explicit on-demand export | File generation begins only after the customer requests it |

## PR-4.3 Required content

The reusable cross-industry template must contain, when relevant and supported by sufficient data:

1. Top three selling products.
2. Bottom three selling products.
3. Revenue, profit, and expenses.
4. Performance charts against the previous equivalent period: week over week or month over month.
5. A deterministic summary of the most material performance changes.
6. Backend-calculated projections.
7. Recommendations selected through predefined business rules.
8. Low-stock products based on configured thresholds.
9. Reporting period, data freshness, and warnings for missing or insufficient data.

Sections that do not apply to a business type are omitted rather than populated with misleading placeholders.

## PR-4.4 Logic and reliability

| ID | Requirement | Acceptance criterion |
|---|---|---|
| PR-4.7 | Generate every scheduled report without AI | All numbers, summaries, projections, and recommendations trace to backend calculations, templates, or rules |
| PR-4.8 | Make report generation idempotent | Tenant + report type + period uniquely identifies one report |
| PR-4.9 | Retry transient failures automatically | Bounded retry policy is tested |
| PR-4.10 | Detect a missing report through an independent recovery job and force regeneration | Reconciliation test proves a deliberately missed job is recovered |
| PR-4.11 | Alert the operator after persistent failure | Alert includes tenant, report type, period, attempts, and failure reason |
| PR-4.12 | Preserve a minimal operational audit record after report expiry | Status, attempts, timestamps, notification state, and failure reason remain available under the applicable retention policy |

These requirements implement PD-007 and ADR-019.

---

# Questions Still Open

* What is the acceptable manual-confirmation rate before the no-template approach is judged to have failed?
* Should an optional template still be offered for customers who prefer structure?
* Which POS export formats should be reverse-engineered first? (Answer comes from `15_Customer_Discovery.md` Section 8.)

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 29/07/2026 | Initial draft. Records PD-006 (no import template) and ED-009 (AI ingestion boundary). |
| 0.2 | 30/07/2026 | Added deterministic scheduled reporting requirements from Change 8. |
| 0.3 | 30/07/2026 | Made business-template terminology and module applicability explicit while preserving one common product and calculation core. |
