# 08_Cost_Analysis.md

**Version:** 1.1 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---

# Document Contract

## Purpose

This document has two parts. First, it maps the competitive landscape in Ireland and internationally — what independent bike shops currently pay for software, and what that software does and does not do — so the company's positioning and pricing are grounded in evidence rather than assumption. Second, it governs the assumptions, structure and conclusions of the company's financial forecast, based on the architecture and deployment model already defined in this repository.

The connected calculation artifact is [`../finance/07_Financial_Forecast.xlsx`](../finance/07_Financial_Forecast.xlsx). The spreadsheet is the editable calculation source of truth; this document explains what is modelled, what the current assumptions mean and which conclusions may be used for planning.

---

## Audience

* Founder
* Investors
* Product Team

---

## In Scope

* Competitor identification (Ireland and international)
* Price and feature comparison
* Gap analysis relative to our planned product
* Summary of competitive advantage
* Fixed, variable, step and business-overhead cost assumptions
* Client-count economics at 0, 5, 10, 25, 50, 100 and 300 customers
* Conservative, expected and optimistic 12-month forecasts
* Unit economics, break-even tests, sensitivity analysis and forecast governance

---

## Out of Scope

This document intentionally does **not** define:

* Alternative pricing tiers and future price changes (see `09_Business_Model.md`)
* Tax, VAT, founder payroll or personal tax advice
* Detailed infrastructure configuration (see `07_Deployment_Guide.md`)
* Final vendor commitments before production procurement

---

## Related Documents

* `../finance/07_Financial_Forecast.xlsx`
* `04_Technology_Stack.md`
* `05_AI_Architecture.md`
* `07_Deployment_Guide.md`
* `09_Business_Model.md`
* `11_Development_Roadmap.md`
* `12_Decision_Register.md`
* `15_Customer_Discovery.md`

---

# Executive Summary (TL;DR)

Independent bike shops in Ireland and internationally already pay for point-of-sale (POS) and EPOS software — typically €30–€340/month depending on sophistication — but that spend buys transaction processing and basic inventory reporting, not forecasting, profitability explanation, or AI-assisted decision support. General-purpose business intelligence tools (Databox, Grow.com, Klipfolio) fill part of that gap but are not built for retail/workshop operations and require the owner to do their own data modelling. Generic AI copilots (Microsoft 365 Copilot and similar) are not connected to the shop's structured business data at all.

This creates a real, evidenced gap: **nothing in the market combines industry-aware retail + workshop analytics with deterministic calculation and AI explanation, at a price an independent shop can justify.** At €80/month, we sit below premium POS tiers and mid-tier general BI tools, while offering something neither category currently provides.

The financial model now uses three explicit planning scenarios instead of two conflicting infrastructure ranges. At 1–10 customers, the model assumes monthly fixed platform cost of **€80 conservative, €45 expected or €30 optimistic**. These are planning assumptions that combine baseline hosting, database, monitoring, email and storage allowances; they are not quotations. Business overhead, payment fees, per-customer usage, customer acquisition and churn are modelled separately.

---

# Part 1 — Competitive Landscape

## Direct Competitors: Bike Shop POS / Management Software

These are the systems bike shops already use daily for sales and inventory, and are the most likely source of "why do I need another subscription?" objections.

| Competitor | Market | Starting Price (approx., monthly) | Core Features | AI / Forecasting / Explanation |
|---|---|---|---|---|
| Lightspeed Retail | International (used in Ireland) | ~$109 Basic / $179 Core / $339 Plus (billed monthly; ~15-18% cheaper annually) | POS, inventory, vendor catalogs, serialized inventory, repair/service tickets, multi-location, marketing/loyalty add-ons | Reporting only; no forecasting, no plain-language explanation, no AI recommendations |
| Ascend (by Shopify) | International | Not publicly listed; typically enterprise-quoted | Bike-shop-specific: quotes, layaway, special orders, service | Standard reporting; not AI-driven |
| Shopify POS | International (used in Ireland) | From ~$29/month (general retail tier) | General retail POS, inventory, omnichannel | Basic analytics app add-ons; not bike-shop-specific, not AI-explained |
| RetailEdge | International | Custom-quoted | Complex inventory, since 1989, general "complex inventory" retailers including bike shops | Traditional reporting |
| Celerant | International | Custom-quoted | POS + repairs/work orders + rentals in one system | Traditional reporting |
| KORONA POS | International | Custom-quoted | POS, inventory automation, purchase orders, loyalty | Reporting/analytics dashboard; not AI-driven |
| Rain POS | International | Custom-quoted | Bike-shop-specific POS, inventory, marketing automation | Reporting; not forecasting or AI-explained |
| MicroBiz Cloud POS | International | Custom-quoted | Bike/eBike-specific, service department management | Reporting |
| Generic Irish EPOS providers (SmartPOS, easyStore/easyPayments, CBE, and similar) | Ireland | ~€30-€250/month depending on tier (basic ~€75-€135, advanced ~€170-€315) | POS, stock tracking, card payment integration, some accounting integration (Xero/QuickBooks) | Basic reporting; not industry-specific analytics, not AI |

**Pattern across this category:** these systems are transaction and inventory systems first. Reporting is a secondary feature bolted onto the POS, not the primary product. None of them explain *why* profit changed, forecast demand with confidence ranges, or generate prioritized, explainable recommendations. None are built to extend the same analytical model to a completely different industry (e.g., a coffee shop's recipe costing) without a full redesign.

## Adjacent Competitors: General SMB Business Intelligence Tools

These don't target bike shops specifically, but a technically confident owner could attempt to use them instead of buying an industry-specific tool.

| Competitor | Starting Price (approx., monthly) | Core Features | Fit for a Bike Shop |
|---|---|---|---|
| Databox | Free tier; paid from ~$64 (Analyst) to ~$399 (Growth) | AI-powered dashboards, natural-language questions, forecasting, anomaly detection, 130+ integrations | Marketing/sales-metrics oriented (HubSpot, GA4, ad platforms); no retail/inventory/repair domain model; owner must build every metric themselves |
| Grow.com | Custom-quoted, positioned similarly to Databox | Drag-and-drop dashboards from various sources | Same gap: general-purpose, no retail/workshop domain logic |
| Klipfolio | ~$120-$600/month by dashboard count | Dashboard-count-based BI pricing | Same gap; also priced per dashboard, which does not map naturally to a single shop's needs |

**Pattern across this category:** genuinely capable BI platforms, but they are horizontal tools that expect the customer (or an agency) to define every metric, connect every data source, and build every dashboard from scratch. There is no bicycle-shop (or any retail-vertical) domain model, no deterministic finding/recommendation engine, and no industry-specific onboarding. This is exactly the "generic chatbot/BI over uploaded files" approach the Company Constitution says the company will not become — but it is also evidence that owners without a dedicated tool are left building this manually.

## Indirect Competitors: Generic AI Copilots

| Competitor | Starting Price (approx.) | What It Offers | Why It Isn't a Real Substitute |
|---|---|---|---|
| Microsoft 365 Copilot (Business) | SMB-priced add-on to an existing Microsoft 365 plan | General productivity AI across Word/Excel/Outlook/Teams; "Analyst" reasoning agents for ad hoc data analysis | Not connected to the shop's transactional data, inventory, or repairs; requires the owner to export/prepare data manually; no deterministic calculation engine or domain-specific findings |

**Pattern:** these tools are a plausible "why not just use ChatGPT/Copilot" objection, but they only analyze what's manually fed to them, in the moment, with no persistent calculation engine, no tenant-isolated business memory, and no guarantee against invented numbers.

## Gap Analysis

| Capability | Bike-shop POS/EPOS | General BI Tools | Generic AI Copilots | Our Platform |
|---|---|---|---|---|
| Sells product / processes payment | Yes | No | No | No (not our scope — we complement POS, not replace it) |
| Retail inventory tracking | Yes | No (unless manually connected) | No | Yes (ingests from existing POS/exports) |
| Workshop/repair tracking | Some (Lightspeed, Celerant, Rain, MicroBiz) | No | No | Yes |
| Deterministic profitability/margin analysis | Basic reporting only | Requires manual setup | No | Yes, purpose-built |
| Demand forecasting with confidence ranges | No | Some (Databox) but not retail-specific | No | Yes |
| Plain-language "why did this happen" explanation | No | Limited (Databox AI summaries, marketing-focused) | Ad hoc only | Yes, tied to calculated findings |
| Industry-specific onboarding (bike shop terminology, templates) | Yes (bike-specific vendors only) | No | No | Yes |
| Reusable across other small-business verticals | No (bike-specific vendors are bike-only; generic POS is generic) | Yes, but with no domain logic | Yes, but with no domain logic | Yes — industry-flexible core with domain logic per template (`02_Operational_Domains.md`) |
| Price point accessible to a single-location independent shop | Mixed (€30-€340/month) | Mixed ($64-$600/month) | Requires existing M365 subscription | €80/month, transparent, single tier initially |

**The gap, stated plainly:** the market has bike-shop-specific transaction software, and it has generic BI/AI tools — but nothing that combines a retail-and-workshop-aware deterministic analytics engine with AI explanation, at a price and simplicity level suited to a single-location independent shop that doesn't want to hire an analyst or learn a BI tool.

## Summary of Competitive Advantage

* We do not compete with the shop's POS — we sit on top of it, which lowers the switching cost of adoption (no need to replace an existing, working system).
* We are the only option in this comparison offering deterministic, explainable profitability and forecasting logic specifically modelled around retail + workshop operations.
* Our AI layer explains calculated findings; it does not require the owner to build dashboards or ask an AI to interpret raw exports.
* Our core is explicitly designed to extend to other verticals (`02_Operational_Domains.md`, `06_Database_Design.md`) without becoming a generic, undifferentiated BI tool.

**Caveat, stated for balance:** this analysis is based on publicly available marketing/pricing pages, not direct trials of each competitor, and pricing changes frequently (most sources above are dated within the last 12 months). It should be revisited as market evidence develops and cross-checked against `15_Customer_Discovery.md` interview findings. €80/month is the accepted current price, while owners' actual willingness to pay for a second subscription alongside their existing POS remains an important commercial validation question.

---

# Part 2 — Financial Forecast

## Connected Calculation Artifact

[`07_Financial_Forecast.xlsx`](../finance/07_Financial_Forecast.xlsx) contains:

* A central assumptions sheet with editable conservative, expected and optimistic inputs.
* Client-count economics at 0, 5, 10, 25, 50, 100 and 300 customers.
* Monthly customer, revenue, cost, profit and cash forecasts for the first 12 months.
* Sensitivity tests, model checks, charts and a source/audit trail.

The spreadsheet must be updated when assumptions change. Static figures in this document are a dated summary of model version 1.0.

## Model Conventions

| Convention | Treatment |
|---|---|
| Current price | €80 per business per month, governed by BD-005 |
| Currency | EUR; USD vendor prices are retained as source evidence and absorbed into planning allowances |
| Forecast period | Monthly for 12 months |
| Revenue recognition | Active closing customers × €80 for planning |
| Tax and VAT | Excluded pending confirmation by an Irish accountant or tax adviser |
| Founder salary | €0 in the base forecast; a €3,000 monthly goal is tested separately |
| Pilot discounts | Excluded; any discount must be added as a separate assumption without changing BD-005 |
| Forecast versus actual | All non-vendor inputs remain assumptions until pilot actuals replace them |

## Cost Classification

| Cost class | Model treatment | Examples |
|---|---|---|
| Fixed platform | Step cost based on active-customer bands | VPS/container hosting, baseline Neon capacity, monitoring, email and storage allowances |
| Variable per customer | Increases with active customers | Stripe, AI explanations, scheduled report generation (in-app, not email), storage/processing and support allowance |
| Step costs | Increase when a customer band requires more capacity | Larger VPS, database tier, monitoring/email upgrade |
| Business overhead | Separate from direct service delivery | Accounting, insurance, legal, administration and basic marketing |
| Acquisition cost | Applied to each new customer | Founder-led sales, visits, advertising and onboarding allowance |
| Founder compensation | Excluded from base; tested separately | €3,000 monthly founder-salary goal |

## Verified Vendor Inputs

As checked on 30/07/2026:

* [Stripe Ireland](https://stripe.com/ie/pricing) lists standard EEA cards at **1.5% + €0.25**, and SEPA Direct Debit at **€0.35**. The base model uses the card rate and keeps SEPA as a future payment-mix test.
* [Cloudflare R2](https://developers.cloudflare.com/r2/pricing/) lists Standard storage at **$0.015 per GB-month**, with 10 GB-month of monthly free storage and free egress. The model uses a broader per-customer storage/processing allowance because R2 storage alone is not the full ingestion cost.
* [Sentry](https://sentry.io/pricing/) lists a $0 Developer tier and a $26/month Team tier.
* [Neon](https://neon.com/pricing) provides a free tier and describes typical paid usage around $15/month; actual cost depends on compute and storage usage.
* [Resend](https://resend.com/pricing) provides a free tier. The forecast nevertheless retains a small per-customer email allowance for transactional email (invitations, alerts, billing notices). Scheduled weekly and monthly reports are delivered in-app, not by email (PD-007/ADR-019), and are costed separately under "Scheduled Reporting Cost Treatment" below.

Vendor prices are time-sensitive. The spreadsheet records the source URL, date, unit and modelling treatment for each input.

## Scenario Assumptions

| Assumption | Conservative | Expected | Optimistic |
|---|---:|---:|---:|
| Monthly churn | 4.0% | 2.5% | 1.5% |
| CAC per new customer | €250 | €150 | €90 |
| AI cost per active customer | €3.00 | €1.50 | €0.75 |
| Email/report cost per active customer | €0.20 | €0.10 | €0.05 |
| Storage and compute per active customer | €1.30 | €0.70 | €0.35 |
| Support allowance per active customer | €0.40 | €0.25 | €0.15 |
| Fixed platform cost at 1–10 customers | €80 | €45 | €30 |
| Business overhead at 1–10 customers | €100 | €75 | €50 |

The planning range for fixed platform cost at 1–10 customers is therefore **€30–€80 per month**, with **€45** as the expected case. This single scenario range replaces the inconsistent €60–€150 and €15–€110 figures previously used.

## Unit Economics at the Current €80 Price

In the expected scenario:

```text
Subscription revenue per customer:          €80.00
Stripe EEA card fee:                         €1.45
AI explanation allowance:                    €1.50
Email/report allowance:                      €0.10
Storage and compute allowance:               €0.70
Support allowance:                           €0.25
--------------------------------------------------
Expected direct variable cost:               €4.00
Expected contribution before fixed costs:   €76.00
Expected contribution margin:                95.0%
```

This is a forecast, not an observed margin. AI, ingestion, reporting and support allowances must be replaced with tenant-level actuals during the pilot.

## Client-Count Economics — Expected Scenario

| Active customers | Monthly revenue | Total monthly cost before acquisition and founder salary | Monthly operating profit | Operating margin | Cost per customer |
|---:|---:|---:|---:|---:|---:|
| 0 | €0 | €120 | -€120 | N/A | N/A |
| 5 | €400 | €140 | €260 | 65.0% | €28 |
| 10 | €800 | €160 | €640 | 80.0% | €16 |
| 25 | €2,000 | €270 | €1,730 | 86.5% | €11 |
| 50 | €4,000 | €490 | €3,510 | 87.8% | €10 |
| 100 | €8,000 | €930 | €7,070 | 88.4% | €9 |
| 300 | €24,000 | €2,400 | €21,600 | 90.0% | €8 |

These static scenarios exclude customer-acquisition spending because CAC depends on how many new customers are added in a month. The 12-month forecast includes CAC explicitly.

## 12-Month Forecast Summary

| Scenario | Month 12 active customers | Month 12 revenue | Month 12 operating profit | 12-month revenue | 12-month operating profit / ending cash |
|---|---:|---:|---:|---:|---:|
| Conservative | 26 | €2,080 | €485 | €11,200 | -€49 |
| Expected | 49 | €3,920 | €2,384 | €21,280 | €9,676 |
| Optimistic | 129 | €10,320 | €6,765 | €46,640 | €28,682 |

The conservative scenario is approximately cash-neutral after 12 months because slower acquisition, higher CAC, higher churn and higher usage costs absorb the operating contribution. The expected and optimistic cases demonstrate potential, not targets or guarantees.

## Break-Even Interpretation

* At five paying customers, the expected static scenario covers direct costs, expected fixed platform cost and expected base business overhead.
* The base forecast excludes founder salary. At the expected cost structure, 50 active customers produce approximately **€3,510/month** before acquisition spending and founder compensation, leaving approximately **€510/month** after the separate €3,000 founder-salary test.
* Break-even month depends on the timing of customer acquisition and CAC, not only the number of active customers.
* Taxes, VAT and founder payroll costs may materially increase the number of customers needed to support founder compensation.

## Sensitivity Tests

The spreadsheet tests or provides explicit input controls for:

* AI cost between €0.50 and €5.00 per active customer.
* Higher infrastructure step costs.
* Larger uploads and higher storage/processing costs.
* Monthly churn increasing from 2.5% to 5.0%.
* A less favourable Stripe/payment-method mix.
* An annual discount equivalent to one month free.
* Higher weekly and monthly report-generation and delivery cost.

## Forecast Governance

The following labels must remain distinct:

* **Verified vendor input:** Current value taken from an official price page.
* **Assumption:** Founder-selected input awaiting evidence.
* **Forecast:** Formula-derived future result.
* **Actual:** Observed invoice, payment, usage or customer result.
* **Variance:** Actual minus forecast.

During the pilot, the company must record actual cost per tenant for AI, data processing, database, storage, report generation, email, support and payment processing. Assumptions should be replaced only when sufficient evidence exists, with changes recorded in the spreadsheet's source and version history.

---

# Business Perspective

The competitive analysis confirms that €80/month sits in a defensible price band. The expected financial scenario also indicates strong contribution economics if usage is controlled and the customer-growth assumptions are achieved.

---

# Customer Perspective

The customer pays €80/month for deterministic, industry-aware decision support that complements existing POS software. The financial model must never justify degrading service quality merely to protect an assumed margin.

---

# Technical Perspective

The backend performs all calculations and business logic. AI is limited to explaining backend-generated findings. Per-tenant metering, usage caps, caching, deterministic report generation and vendor-routing controls are commercially necessary because they protect the unit economics without transferring calculation responsibility to AI.

---

# Commercial Perspective

Infrastructure is not the only cost driver. CAC, churn, business overhead, payment mix and the timing of client acquisition materially affect cash generation. Financial planning must therefore use the connected forecast rather than multiplying €80 by a target customer count and treating the result as profit.

---

# Current Decisions

* Set the current subscription price at €80/month per business (BD-005, Accepted).
* Use the connected spreadsheet as the calculation source of truth for cost and revenue scenarios.
* Separate fixed platform, variable, step, business-overhead, acquisition and founder-compensation costs.
* Exclude tax and VAT until professionally confirmed, while clearly disclosing the exclusion.
* Replace assumptions with measured pilot actuals and track variance.

---

# Risks

* Customer acquisition may be slower or more expensive than assumed.
* Churn may be higher than assumed.
* AI, ingestion, storage, database or reporting usage may exceed allowances.
* Infrastructure upgrades may be required earlier than the client-count steps assume.
* Vendor pricing and exchange rates may change.
* Tax, VAT, insurance, accounting and payroll treatment may reduce operating profit.
* Owners may resist a second subscription even when the product has clear value.

---

# Scheduled Reporting Cost Treatment

Weekly and monthly reports use deterministic backend calculations, reusable presentation templates, and in-app notifications. They do not require AI calls, transactional report-delivery emails, or automatically generated files. The forecast's reporting allowance therefore covers worker execution, database queries, in-app notification records, short-lived report payloads, monitoring, recovery retries, and occasional on-demand PDF/Word exports.

The spreadsheet label "Email/report cost per active customer" should be interpreted as a conservative combined notification/report-runtime allowance until the next workbook revision renames that input. It must not be interpreted as a scheduled email or AI cost. Pilot metering must separately capture scheduled job compute, recovery attempts, seven-day report storage, notification volume, and requested export generation.

This treatment lowers normal reporting cost while preserving a modest allowance for real usage and failure recovery. PD-007 and ADR-019 govern the reporting behaviour.

---

# Questions Still Open

* What CAC and monthly churn are observed during the first paying cohort?
* What are actual AI, ingestion, reporting and support costs per tenant?
* What Irish tax, VAT, founder-payroll and insurance costs must be added?
* Should pilot customers receive a temporary discount while the public price remains €80?
* What customer or usage thresholds actually trigger each infrastructure step?
* What monthly cash reserve should be maintained before the company funds founder compensation?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial draft; competitive landscape and cost estimate based on public pricing research. |
| 0.2 | 30/07/2026 | Confirmed €80/month as the accepted current price and aligned pricing language with BD-005. |
| 1.0 | 30/07/2026 | Reconciled the fixed-cost range; added governed assumptions, client-count economics, three 12-month scenarios, unit economics, break-even interpretation, sensitivities, forecast governance and the connected financial forecast spreadsheet. |
| 1.1 | 30/07/2026 | Fixed the Resend vendor-input note and the Cost Classification table's "Examples" column, both of which incorrectly implied weekly/monthly reports are emailed — reports are in-app only (PD-007/ADR-019); confirmed the "Scheduled Reporting Cost Treatment" section is consistent with this. |
