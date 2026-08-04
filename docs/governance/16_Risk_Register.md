# 16_Risk_Register.md

**Version:** 0.2 (Draft)
**Status:** Draft
**Phase:** Company Governance
**Author:** Founder & CTO
**Last Updated:** 04/08/2026

---

# Document Contract

## Purpose

This is the **single canonical register** of every risk raised across `docs/governance/`. Each governance document identifies risks specific to its own topic (pricing, architecture, deployment, naming, etc.) in its own "Risks" section — this register consolidates all of them into one place so they can be tracked, mitigated, and closed over time instead of sitting scattered across twelve separate files.

Risks stay recorded in their **source document** as well — this register does not replace them, it aggregates them for tracking. If a risk's status changes here, the source document should be updated to match (or vice versa) so the two never contradict each other.

## Audience

* Founder
* Product Team
* Engineering Team
* Future Employees
* Investors

## In Scope

* Every risk currently listed in a "Risks" section across `docs/governance/`
* Source document and any mitigation already recorded for each
* Status tracking (Open / Mitigated / Retired) as evidence arrives

## Out of Scope

* New risk analysis not already recorded in a source document (add it to the source document first, then bring it here)
* Financial risk modelling detail (see `08_Cost_Analysis.md`)
* Legal/compliance risk requiring professional advice (see `13_Branding_Strategy.md`'s clearance caveat, `11_Development_Roadmap.md` Phase 5)

## Related Documents

* All documents in `docs/governance/`
* `12_Decision_Register.md`
* `17_Open_Questions.md`

---

# How to Use This Register

1. **Adding a risk:** record it in its source document's "Risks" section first (per `ED-002`/`ED-003` documentation standard), then add a row here with the same wording.
2. **Status values:**
   | Status | Meaning |
   |---|---|
   | Open | Identified, no mitigation in place yet |
   | Mitigating | A mitigation approach is defined and already in the source document (does not mean the risk is closed — see the Mitigation column) |
   | Retired | The risk no longer applies (e.g., the decision that created it was superseded) — move the row to "Retired Risks" with a reason |
3. **Closing a risk:** move its row to the "Retired Risks" section with the date and the evidence/decision that closed it. Do not delete rows — a retired risk with its reasoning is more useful than a silently removed one.
4. This is a snapshot as of 30/07/2026. No risk in this initial pass has been retired yet — every current risk in the governance set genuinely remains open pending pilot evidence, engineering work, or a formal decision.

---

# Open Risks

| ID | Risk | Mitigation (as recorded in source) | Source | Status |
|---|---|---|---|---|
| R-001 | Customers may have poor-quality operational data. | Reduced through explainability, measurable ROI, customer collaboration and iterative product development (general strategy, not risk-specific). | `01_Project_Vision.md` | Open |
| R-002 | Small businesses may initially distrust AI recommendations. | Same general strategy as R-001. | `01_Project_Vision.md` | Open |
| R-003 | Existing workflows may be difficult to change. | Same general strategy as R-001. | `01_Project_Vision.md` | Open |
| R-004 | Customers may underestimate the financial value of better decisions. | Same general strategy as R-001. | `01_Project_Vision.md` | Open |
| R-005 | Reconciling two "five domains" terminologies retroactively may cause confusion if older documents are read without the reconciliation section. | `02_Operational_Domains.md` is now the canonical reference; other documents should link here rather than restate domain lists. | `02_Operational_Domains.md` | Mitigating |
| R-006 | Treating Returns & Warranty as a sub-topic of Financial Performance rather than its own domain may under-emphasise it in early dashboard design. | `10_Product_Requirements.md` still gives it a full module treatment with its own metrics and recommendations. | `02_Operational_Domains.md` | Mitigating |
| R-007 | Relying on a third-party router (OpenRouter) introduces a dependency. | Router sits behind the internal `AIProvider` interface and can be replaced. | `03_System_Architecture.md` | Mitigating |
| R-008 | "Cheapest model that meets a quality threshold" requires the threshold to be defined and tested, or cost optimisation could quietly degrade explanation quality. | Must be paired with the output validation rules in `05_AI_Architecture.md` before OpenRouter routing is enabled in production. | `03_System_Architecture.md` | Open |
| R-009 | Assembling several best-of-breed services (rather than one platform) increases integration surface area. | Keep every vendor behind a narrow internal boundary (repository, gateway, adapter) per `12_Decision_Register.md`. | `04_Technology_Stack.md` | Mitigating |
| R-010 | Some categories (Neon, Supabase, R2) are still relatively young companies compared to hyperscalers. | Standard, portable APIs (SQL, S3) mean migration is possible if needed. | `04_Technology_Stack.md` | Mitigating |
| R-011 | A cost-first AI routing strategy could degrade explanation quality if the quality threshold is not enforced strictly. | Pair routing with the output validation rules before enabling cost-optimised routing in production. | `05_AI_Architecture.md` | Open |
| R-012 | Introducing a third-party router (OpenRouter) adds one more vendor dependency. | Sits behind the internal interface and is replaceable without touching business modules. | `05_AI_Architecture.md` | Mitigating |
| R-015 | A solo founder operating a VPS directly introduces key-person operational risk. | Coolify and documented configuration make the deployment reconstructable by someone else if needed. | `07_Deployment_Guide.md` | Mitigating |
| R-016 | Multiple external vendors (eight-plus services) increase the number of things that can fail independently. | Uptime Kuma and Sentry provide visibility; every service sits behind a replaceable boundary. | `07_Deployment_Guide.md` | Mitigating |
| R-017 | Manual DNS/TLS misconfiguration could cause downtime. | Automated certificate renewal via the reverse proxy reduces manual intervention. | `07_Deployment_Guide.md` | Mitigating |
| R-018 | Customer acquisition may be slower or more expensive than assumed. | Not yet specified — tracked via pilot CAC measurement (`08_Cost_Analysis.md` Questions Still Open). | `08_Cost_Analysis.md` | Open |
| R-019 | Churn may be higher than assumed. | Not yet specified — tracked via pilot churn measurement. | `08_Cost_Analysis.md` | Open |
| R-020 | AI, ingestion, storage, database or reporting usage may exceed allowances. | Not yet specified — pilot metering planned (per `08_Cost_Analysis.md`'s Forecast Governance and the Scheduled Reporting Cost Treatment section). | `08_Cost_Analysis.md` | Open |
| R-021 | Infrastructure upgrades may be required earlier than the client-count steps assume. | Not yet specified. | `08_Cost_Analysis.md` | Open |
| R-022 | Vendor pricing and exchange rates may change. | Not yet specified — vendor inputs are dated and sourced, but not hedged. | `08_Cost_Analysis.md` | Open |
| R-023 | Tax, VAT, insurance, accounting and payroll treatment may reduce operating profit. | Excluded from the base forecast pending professional (Irish accountant/solicitor) advice — see `11_Development_Roadmap.md` Phase 5. | `08_Cost_Analysis.md` | Open |
| R-024 | Owners may resist a second subscription even when the product has clear value. | Not yet specified — this is the single biggest open commercial risk (see also R-025). | `08_Cost_Analysis.md` | Open |
| R-025 | The biggest risk to the business model is demand risk, not cost or pricing risk. | Only `15_Customer_Discovery.md` (Phase 1 interviews) can resolve this — no document-level mitigation possible yet. | `09_Business_Model.md` | Open |
| R-026 | Founder time is the scarcest resource in the first 12 months; the forecast assumes founder-led acquisition with no paid marketing, which may not scale even in the optimistic scenario. | Not yet specified. | `09_Business_Model.md` | Open |
| R-027 | Schema detection may prove harder than estimated against real-world POS exports. | Layered approach (alias dictionaries → structural heuristics → AI-assisted suggestion) plus saved mapping profiles, and honest plain-language fallback to user confirmation. | `10_Product_Requirements.md` | Mitigating |
| R-028 | The AI-suggestion boundary in data ingestion could erode over time under delivery pressure ("just let the model clean it"). | PR-6.4 makes this a tested engineering constraint, not just a convention. | `10_Product_Requirements.md` | Mitigating |
| R-029 | Customers may upload data containing personal information the platform does not need. | Data minimisation at ingestion; do not import fields the template does not require. | `10_Product_Requirements.md` | Mitigating |
| R-030 | Skipping or shortening Phase 1 (customer discovery) is the most likely and most damaging roadmap failure mode. | None besides discipline — flagged explicitly as tempting because building feels productive and interviewing feels slow. | `11_Development_Roadmap.md` | Open |
| R-031 | Solo-founder capacity means phases will likely take longer than planned. | Roadmap deliberately has no fixed dates for this reason. | `11_Development_Roadmap.md` | Mitigating |
| R-032 | Gate criteria (A–D) can be rationalised away under pressure. | Should be assessed honestly, ideally with a second opinion. | `11_Development_Roadmap.md` | Open |
| R-033 | Delaying naming too long means writing marketing material with a placeholder, which wastes effort. | Not yet specified. | `13_Branding_Strategy.md` | Open |
| R-034 | Registering domains before trademark clearance risks spending on a name that must later be abandoned. | Naming process sequences formal clearance before domain/handle registration. | `13_Branding_Strategy.md` | Mitigating |
| R-035 | All four shortlisted candidate names (Tara, Nora, Orla, Vera) are real given names, raising the chance of existing registrations in some class. | Formal clearance (CRO, IPOI, EUIPO) is treated as non-optional before any spend. | `13_Branding_Strategy.md` | Mitigating |
| R-036 | `prescription_details` (ADR-023) stores prescription data, a GDPR Article 9 special category; minimal fields alone do not make it compliant, since it's still linkable to a customer via `sale_items -> sales -> customers`. | Table deliberately excludes patient identity/clinical fields. Full legal basis, DPIA, and retention/deletion policy remain open — see Q-053 — blocked on legal advice, not an engineering decision. | `06_Database_Design.md` | Open |

---

# Retired Risks

| ID | Risk | Source | Retired Date | Reason |
|---|---|---|---|---|
| R-013 | Generalising "repairs"/"recipes" into "Production Events" too early, before more than two business types exist, risks over-engineering a pattern that doesn't actually recur cleanly. | `06_Database_Design.md` | 04/08/2026 | ADR-016 accepted once cafe and pharmacy were both being actively scoped, satisfying the stated gate ("only invest once a second real customer segment is being actively built"). |
| R-014 | Existing documentation still described repairs as bicycle-specific and would need updating once the Production Events generalisation (ADR-016) is accepted. | `06_Database_Design.md` | 04/08/2026 | ADR-016 accepted; `06_Database_Design.md` and `12_Decision_Register.md` updated in the same change. |

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 30/07/2026 | Initial register. Consolidated all 35 risks currently listed across `docs/governance/` (01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 13) into one tracked table with source attribution and status. |
| 0.2 | 04/08/2026 | Retired R-013 and R-014 (Production Events over-engineering/documentation risks) now that ADR-016 is accepted and the relevant docs are updated. Added R-036: GDPR special-category compliance for the new `prescription_details` table (ADR-023) — open, blocked on legal advice. |
