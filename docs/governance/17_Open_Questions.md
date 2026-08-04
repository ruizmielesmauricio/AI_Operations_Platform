# 17_Open_Questions.md

**Version:** 0.3 (Draft)
**Status:** Draft
**Phase:** Company Governance
**Author:** Founder & CTO
**Last Updated:** 04/08/2026

---

# Document Contract

## Purpose

This is the **single canonical register** of every open question raised across `docs/governance/`. Each governance document ends with its own "Questions Still Open" section — this register consolidates all of them into one place so they can be tracked and answered over time instead of sitting scattered across fourteen separate files, and so answered questions are visibly moved to a **Resolved** section rather than silently disappearing.

Questions stay recorded in their **source document** as well — this register does not replace them, it aggregates them for tracking. When a question is answered, update both: move the row here to Resolved, and update or remove it from the source document's own "Questions Still Open" list so the two never contradict each other.

## Audience

* Founder
* Product Team
* Engineering Team
* Future Employees
* Investors

## In Scope

* Every question currently listed in a "Questions Still Open" section across `docs/governance/`
* The two items in `12_Decision_Register.md`'s "Decisions Requiring Action" table (ADR-015, ADR-016) — these are pending decisions rather than open-ended questions, but function the same way (blocked on evidence, tracked until resolved)
* Resolved questions, with the resolution and its source

## Out of Scope

* New questions not already recorded in a source document (add it to the source document first, then bring it here)
* Detailed interview scripting (see `15_Customer_Discovery.md`)

## Related Documents

* All documents in `docs/governance/`
* `12_Decision_Register.md`
* `16_Risk_Register.md`

---

# How to Use This Register

1. **Adding a question:** record it in its source document's "Questions Still Open" section first, then add a row here with the same wording.
2. **Resolving a question:** move its row to the "Resolved Questions" section with the date, the answer, and the decision or evidence that answered it (cite a BD/PD/ADR/ED ID from `12_Decision_Register.md` where applicable). Then remove or update the corresponding line in the source document so it doesn't still read as open.
3. **Do not delete rows.** A resolved question with its answer recorded is more useful than one silently removed — it's part of the company's decision history.
4. This is a snapshot as of 30/07/2026. Most current questions are genuinely still open because they depend on evidence that doesn't exist yet — Phase 1 customer discovery (`11_Development_Roadmap.md`) hasn't started. One question has already been resolved and is used below as the worked example of how this register is meant to be used.

---

# Open Questions

| ID | Question | Source | Notes |
|---|---|---|---|
| Q-001 | Which company/product name will be selected from the shortlisted candidates (Tara, Nora, Orla, Vera) and formally cleared? | `00_Company_Constitution.md` | Same underlying question as Q-041/Q-042 in `13_Branding_Strategy.md`. |
| Q-002 | What will the company branding look like? | `00_Company_Constitution.md` | Depends on Phase 5 (`11_Development_Roadmap.md`). |
| Q-003 | Which AI provider will become the default for Version 1? | `00_Company_Constitution.md` | Related to Q-012/Q-017 (quality threshold) and ADR-015 (Q-050). |
| Q-004 | What metrics will define customer success after launch? | `00_Company_Constitution.md` | Related to Q-008 (product-market-fit metrics). |
| Q-005 | Should the accepted €80/month price later include annual-billing discounts or additional tiers? | `01_Project_Vision.md` | Price itself is settled (BD-005, Accepted, €80/month); this is about future packaging only. |
| Q-006 | Which customer segment should we target first within the bike shop market? | `01_Project_Vision.md` | Related to Q-045 (`15_Customer_Discovery.md`). |
| Q-007 | What measurable ROI should every customer expect within their first year? | `01_Project_Vision.md` | |
| Q-008 | What customer success metrics will determine product-market fit? | `01_Project_Vision.md` | Related to Q-004. |
| Q-009 | Should Returns & Warranty be its own top-level domain once pilot data is available? | `02_Operational_Domains.md` | Provisionally assigned to Financial Performance; open to revision. |
| Q-010 | Should Business Knowledge remain purely internal, or become a customer-visible module? | `02_Operational_Domains.md` | |
| Q-011 | Does "Retail Operations" and "Workshop Operations" naming generalise cleanly to non-bike-shop templates? | `02_Operational_Domains.md` | Directly relevant to the bike-shop-only naming concern tracked across prior audits. |
| Q-012 | What is the minimum acceptable quality threshold, and how is it measured before launch (AI routing)? | `03_System_Architecture.md` | Duplicate topic of Q-017; kept separate because each document phrases it for its own scope. Also see ADR-015 (Q-050). |
| Q-013 | Which EU regulatory requirements specifically constrain AI model selection, and how are they encoded into the routing rules? | `03_System_Architecture.md` | Duplicate topic of Q-018. |
| Q-014 | Should there be a manual override to force a specific AI model for certain customers or use cases? | `03_System_Architecture.md` | Duplicate topic of Q-019. |
| Q-015 | Which background job library (Celery, Dramatiq, RQ, or database-backed) will be formally selected, and when? | `04_Technology_Stack.md` | No ADR yet. |
| Q-016 | Which monitoring stack will be adopted once the pilot phase begins? | `04_Technology_Stack.md` | |
| Q-017 | What is the minimum acceptable quality/reliability threshold for AI routing, and how will it be measured before launch? | `05_AI_Architecture.md` | Duplicate topic of Q-012. This document is the canonical source for AI provider routing detail. |
| Q-018 | Which specific EU regulatory requirements should be encoded as hard constraints on AI model selection, versus soft preferences? | `05_AI_Architecture.md` | Duplicate topic of Q-013. |
| Q-019 | Should certain customers or plans be able to request a specific AI model tier, overriding the default cost-optimised routing? | `05_AI_Architecture.md` | Duplicate topic of Q-014. |
| Q-021 | Should ingredient/parts costing feed directly into the Profitability domain the same way for both business types, or does recipe costing need its own treatment? | `06_Database_Design.md` | Still open — deferred to Stage C9 calculation work. |
| Q-023 | Should staging environment costs be absorbed now, or only introduced once the pilot phase begins? | `07_Deployment_Guide.md` | |
| Q-024 | At what customer count does self-hosting on a VPS stop being the right tradeoff versus a managed application host? | `07_Deployment_Guide.md` | |
| Q-025 | Should Redis be introduced now, or deferred until the background job architecture actually requires it? | `07_Deployment_Guide.md` | |
| Q-026 | What CAC and monthly churn are observed during the first paying cohort? | `08_Cost_Analysis.md` | Depends on Phase 1/4 pilot data. |
| Q-027 | What are actual AI, ingestion, reporting and support costs per tenant? | `08_Cost_Analysis.md` | |
| Q-028 | What Irish tax, VAT, founder-payroll and insurance costs must be added? | `08_Cost_Analysis.md` | Requires professional advice, not an AI answer (per `14_Skills_Tools_Vendor_Stack_Checklist.md`). |
| Q-029 | Should pilot customers receive a temporary discount while the public price remains €80? | `08_Cost_Analysis.md` | Duplicate topic of Q-032. |
| Q-030 | What customer or usage thresholds actually trigger each infrastructure step? | `08_Cost_Analysis.md` | |
| Q-031 | What monthly cash reserve should be maintained before the company funds founder compensation? | `08_Cost_Analysis.md` | |
| Q-032 | Should pilot customers be charged at all, and if so, at what rate relative to €80/month? | `09_Business_Model.md` | Duplicate topic of Q-029 and Q-039. |
| Q-033 | What conversion rate from pilot to paying customer is realistic? (Document assumes 25–60% across scenarios, itself unvalidated.) | `09_Business_Model.md` | |
| Q-034 | At what point should the founder consider paid customer acquisition, given zero paid marketing spend assumed in the first 12 months? | `09_Business_Model.md` | |
| Q-035 | What is the acceptable manual-confirmation rate before the no-template ingestion approach is judged to have failed? | `10_Product_Requirements.md` | Review trigger already defined as <~80% auto-detection success. |
| Q-036 | Should an optional import template still be offered for customers who prefer structure? | `10_Product_Requirements.md` | |
| Q-037 | Which POS export formats should be reverse-engineered first? | `10_Product_Requirements.md` | Answer comes from `15_Customer_Discovery.md` Section 8 — same dependency as Q-048. |
| Q-038 | How many customer interviews are genuinely enough before Gate A — 15, or fewer if patterns emerge clearly? | `11_Development_Roadmap.md` | |
| Q-039 | Should pilot customers be charged during Phase 4? | `11_Development_Roadmap.md` | Duplicate topic of Q-029/Q-032. |
| Q-041 | Company name and product name: separate, or the same? | `13_Branding_Strategy.md` | |
| Q-042 | Which two naming candidates go forward to formal clearance? | `13_Branding_Strategy.md` | Same underlying question as Q-001. |
| Q-043 | Should the `.ie` domain be prioritised over `.com` for an Ireland-first launch? | `13_Branding_Strategy.md` | |
| Q-044 | Should the name be tested with interviewees in Phase 1, or would that leak the product before it's ready? | `13_Branding_Strategy.md` | |
| Q-045 | Which customer segment experiences the greatest operational pain? | `15_Customer_Discovery.md` | Duplicate topic of Q-006. |
| Q-046 | Which problem has the highest willingness to pay? | `15_Customer_Discovery.md` | |
| Q-047 | Which feature would customers use every day? | `15_Customer_Discovery.md` | |
| Q-048 | Which feature creates the strongest competitive advantage? | `15_Customer_Discovery.md` | Related to Q-037. |
| Q-049 | Which assumptions need to be revised before development begins? | `15_Customer_Discovery.md` | |
| Q-050 | ADR-015 (OpenRouter): what numeric quality/reliability threshold and evaluation test set moves this from Proposed to Accepted? | `12_Decision_Register.md` (Decisions Requiring Action) | Pending decision, not an open-ended question. Same topic as Q-003/Q-012/Q-017. |
| Q-052 | When should Stripe Tax registration (Ireland domestic, or OSS) be added? Stripe currently charges 0% VAT since no registration exists. | `04_Technology_Stack.md` | Blocked on LTD company incorporation and accountant advice, not an engineering decision. Related to Q-028. |
| Q-053 | Full GDPR special-category compliance for `prescription_details` (ADR-023): legal basis, DPIA, and retention/deletion policy. Minimal fields alone do not resolve this — the table is still linkable to a customer via `sale_items -> sales -> customers`. | `06_Database_Design.md` | Blocked on legal/DPO advice, not an engineering decision — same treatment as Q-052. |

---

# Resolved Questions

| ID | Question | Source | Resolution | Resolved Date |
|---|---|---|---|---|
| RQ-001 | Which country will be our first commercial market? | Formerly `00_Company_Constitution.md` | Ireland — already established as the first market in `01_Project_Vision.md` ("Independent bike shop in Ireland (initial segment)") and in `CLAUDE.md`. Removed from the Constitution's open questions on 30/07/2026 as duplicative of an already-answered question. | 30/07/2026 |
| Q-020 | Is "Production Events" the right name and shape for the canonical repairs/recipes concept, or does it need refinement once a coffee-shop template is built? | Formerly `06_Database_Design.md` | ADR-016 Accepted as `production_events`/`production_event_inputs`/`production_event_outputs`, implemented in `backend/app/models/production_event.py`. Refined further via pharmacy validation (see Q-040's resolution) — confirmed the name/shape holds without needing a third table. | 04/08/2026 |
| Q-022 | At what point should Production Events become a formal ADR rather than a proposed pattern? | Formerly `06_Database_Design.md` | Once a second and third vertical (cafe, pharmacy) began active scoping, per `06_Database_Design.md`'s own stated gate. ADR-016 moved Proposed → Accepted 04/08/2026. | 04/08/2026 |
| Q-040 | Should the second business template be chosen during Phase 4, to inform ADR-016 before Phase 7? | Formerly `11_Development_Roadmap.md` | Overtaken by events — cafe and pharmacy were both scoped during Phase 2/3 (schema-prep, `11_Development_Roadmap.md` C8b) rather than waiting for Phase 4, since a real pharmacy prospect surfaced the lot/expiry need directly. ADR-016/022/023 accepted as a result. | 04/08/2026 |
| Q-051 | ADR-016 (Production Events): what third-business-type validation and which document updates move this from Proposed to Accepted? | Formerly `12_Decision_Register.md` (Decisions Requiring Action) | Pharmacy served as the third-vertical validation (and, notably, confirmed it does *not* need Production Events — only `inventory_lots`/`prescription_details`, evidence the pattern isn't over-fit). `06_Database_Design.md` and `12_Decision_Register.md` updated; `10_Product_Requirements.md` reviewed and needs no change (no repairs-specific content exists there). | 04/08/2026 |

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 30/07/2026 | Initial register. Consolidated all 49 questions currently listed across `docs/governance/` (00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 13, 15), plus the 2 pending-decision items in `12_Decision_Register.md`'s "Decisions Requiring Action" table, into one tracked list with source attribution and cross-references between duplicate topics. Seeded the Resolved Questions section with one already-answered question (first commercial market = Ireland) as the worked example. |
| 0.2 | 30/07/2026 | Added Q-052 (Stripe Tax registration timing), raised during initial Stripe account setup and blocked on LTD incorporation and accountant advice. |
| 0.3 | 04/08/2026 | Resolved Q-020, Q-022, Q-040, Q-051 — ADR-016 (Production Events) accepted, validated against pharmacy as the third vertical. Added Q-053: GDPR special-category compliance for the new `prescription_details` table (ADR-023), blocked on legal advice. |
