# 09_Business_Model.md

**Version:** 0.1 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** TBD

---

# Document Contract

## Purpose

This document validates the business model described in `02_Business_Model.md` against the competitive and cost evidence gathered in `08_Cost_Analysis.md`, tests the €80/month pricing assumption, estimates revenue for the first six and twelve months, and sets out a review plan for revisiting all of it as real evidence arrives.

This document does not invent confidence that doesn't exist yet — every number below is a planning assumption, not a commitment or a prediction, and is labelled as such throughout.

---

## Audience

* Founder
* Investors
* Product Team

---

## In Scope

* Validation of the core business model against market evidence
* Validation of the €80/month pricing assumption
* First 6-month and first 12-month revenue forecast, scenario-based
* A review plan for revisiting these assumptions

---

## Out of Scope

This document intentionally does **not** define:

* Competitor identification or feature comparison (see `08_Cost_Analysis.md`)
* Infrastructure/operating cost estimates (see `08_Cost_Analysis.md`)
* Legal, tax, or company registration matters (see `10_Roadmap.md`, Phase 5)
* Detailed customer interview questions (see `15_Customer_Discovery.md`)

---

## Related Documents

* 02_Business_Model.md (detailed set)
* 08_Cost_Analysis.md
* 10_Roadmap.md
* 15_Customer_Discovery.md
* 12_Architecture_Decision_Log.md

---

# Executive Summary (TL;DR)

The business model — a €80/month subscription for independent bike shops, sold as a complement to their existing POS rather than a replacement — is consistent with the competitive evidence gathered in `08_Cost_Analysis.md`. The price sits inside a defensible band, and the estimated cost structure supports strong gross margin.

What is **not yet validated** is customer demand: no interviews have been completed, no pilot has run, and no one has actually paid €80/month for this product. This document forecasts revenue under three scenarios — conservative, base, and optimistic — explicitly built on stated assumptions about interview-to-pilot-to-paying conversion, because no real conversion data exists yet. The review plan at the end defines exactly when and how these assumptions get replaced with evidence.

*This is planning information to support the founder's own decisions, not financial advice. The founder should treat all forecasts below as scenario planning, not as a guarantee of outcome.*

---

# Part 1 — Business Model Validation

## The Model, Restated

* **Customer:** Independent bike shop in Ireland (initial segment), paying a monthly subscription.
* **Price:** €80/month working reference price (updated from the €79 figure in `02_Business_Model.md` — see note below).
* **Value delivered:** Deterministic profitability, inventory, repair, and returns analytics, explained in plain language, layered on top of the shop's existing POS/accounting data.
* **Cost structure:** Low fixed infrastructure cost, small variable AI/processing cost per customer (`08_Cost_Analysis.md`).

**Note on the €79 vs. €80 reference price:** `02_Business_Model.md` records €79/month as "a planning assumption and not a permanently approved public price" (BD-001, Proposed). This document updates the working reference to €80/month per current direction. This is a small, cosmetic change in absolute terms, but `02_Business_Model.md` and `11_ADRs.md` / `12_Architecture_Decision_Log.md` should be updated to avoid two different reference prices circulating in the repository — flagged in "Future Improvements" below.

## Validation Against Market Evidence

| Model Assumption | Supporting Evidence | Status |
|---|---|---|
| Bike shops already pay for software and are comfortable with SaaS subscriptions | Confirmed — the entire EPOS/POS category (`08_Cost_Analysis.md`) is subscription-based, €30-€340/month | Validated by market structure |
| €80/month is affordable relative to existing software spend | Sits below premium POS tiers ($179-$339), above basic EPOS entry tiers (€30-€135), comparable to mid-tier general BI tools | Validated by pricing comparison, **not yet validated by actual willingness to pay** |
| A dedicated, explainable analytics layer is a real gap | No competitor combines retail+workshop domain modelling with deterministic calculation and AI explanation | Validated by feature gap analysis |
| Owners will adopt a second subscription alongside their POS | Not yet tested with real owners | **Not validated — this is the single biggest open risk** |
| Bicycle shops are a good validation market before expanding | Combines retail, inventory, seasonal demand, and workshop operations in one accessible segment (`00_Project_Overview.md`) | Reasoned, not yet evidenced |

**Overall assessment:** the model is well-supported on the supply side (there is room in the market, the price is reasonable, the gap is real) but entirely unvalidated on the demand side (no evidence yet that owners will actually buy it). This is expected at this stage of the roadmap — Phase 1 (`10_Roadmap.md`) is documentation and decisions, Phase 2 is customer discovery — but it means every number in Part 2 below is a scenario, not a forecast in the normal sense.

---

# Part 2 — Pricing Assumption Validation

## Is €80/Month Reasonable?

Based on `08_Cost_Analysis.md`:

* It is **higher** than basic Irish EPOS tiers (€30-€135/month), which is appropriate since this product is additive to (not a replacement for) that spend.
* It is **lower** than premium bike-shop-specific POS tiers ($179-$339/month) and most mid-to-upper general BI tools ($159-$600/month), which supports easy justification as "much cheaper than a BI platform, more useful than my POS's built-in reports."
* It is a **single flat tier** initially, which matches the Pricing Principles in `02_Business_Model.md` ("pricing should be understandable... avoid pricing that requires users to estimate technical consumption").

## What Pricing Validation Still Requires

Per `02_Business_Model.md`'s Customer Validation section, the founder still needs to:

* Directly ask bike shop owners what they currently spend on software and what an extra €80/month would need to deliver to be worth it.
* Test whether a lower introductory/pilot price is needed to get the first cohort through the door, versus charging full price from day one.
* Confirm whether annual billing (at a discount, per `02_Business_Model.md`) changes willingness to commit.

**This validation has not yet happened** and is tracked as an open item below and in `15_Customer_Discovery.md`.

---

# Part 3 — Revenue Forecast (First 6 and 12 Months)

## Important Framing

These forecasts are **scenario planning exercises**, not predictions. They exist to help the founder reason about what different outcomes would mean for the business, and to give a review plan something concrete to check itself against. They are built on stated, adjustable assumptions — not on any actual sales data, since none exists yet.

## Shared Assumptions

* Price: €80/month per business (flat), no tiering assumed yet.
* Per `10_Roadmap.md`, Phase 3/4 recruits 3-5 pilot businesses; pilots may run at a reduced rate or free during validation, not full price.
* Paid conversion is assumed to begin only after pilot validation (Phase 4 → Phase 6), not from month 1.
* No paid marketing spend is assumed in this early window — acquisition is assumed to be founder-led outreach and pilot referrals.
* Churn is not modelled in the 6-month window (too early for meaningful churn data) but is included as a simple assumption in the 12-month window.

## Six-Month Scenario Table

| Month | Conservative | Base | Optimistic |
|---|---|---|---|
| 1-2 | 0 paying customers (discovery/prototype, per Phase 1-2) | 0 paying customers | 0-1 pilot customer at reduced rate |
| 3 | 1-2 pilot customers at reduced/waived rate | 2-3 pilot customers at reduced rate | 3 pilot customers at reduced rate |
| 4 | 2 pilot customers | 3-4 pilot customers | 4-5 pilot customers |
| 5 | 2 pilot customers, 0 full-price | 3-4 pilot, 1 converts to full price | 4-5 pilot, 2 convert to full price |
| 6 | 2 pilot, 1 full-price conversion (€80) | 4 pilot, 2 full-price conversions (€160) | 5 pilot, 3 full-price conversions (€240) |
| **MRR at Month 6** | **~€80** | **~€160** | **~€240** |

**Reading this table:** in every scenario, the first six months are dominated by pilot activity, not revenue — this matches `10_Roadmap.md`'s own sequencing (Phase 3-4 before Phase 6 launch). Meaningful MRR is not expected in month 6 under any realistic scenario; the table exists to make that explicit rather than to imply otherwise.

## Twelve-Month Scenario Table

| Scenario | Assumption for Months 7-12 | Paying Customers at Month 12 | MRR at Month 12 |
|---|---|---|---|
| Conservative | Slow word-of-mouth conversion; 1 new paying customer every ~2 months after month 6 | ~4 | ~€320 |
| Base | Public launch (Phase 6) around month 7-8; ~2 new paying customers per month post-launch, ~5% monthly churn | ~12-15 | ~€960-€1,200 |
| Optimistic | Public launch around month 6-7; ~3-4 new paying customers per month, low early churn (~2-3%) | ~20-25 | ~€1,600-€2,000 |

**Reading this table:** even the optimistic scenario produces modest absolute revenue (~€1,600-€2,000 MRR) by month 12 — this is consistent with a single-founder, single-segment, pre-product-market-fit business, not a growth-stage SaaS company. This is intentional: the roadmap explicitly sequences validation before scale (`10_Roadmap.md`, Milestone Gates), and this forecast should not be read as a target to hit, but as a planning range to test the model against.

## What Would Change These Numbers Materially

* A faster or slower Phase 3-4 pilot process (`10_Roadmap.md`) shifts the whole timeline left or right.
* Whether pilot customers are charged at all during validation (open question, `08_Cost_Analysis.md`).
* Real churn once customers experience a full billing cycle — assumed conservatively above, not measured.
* Whether expansion beyond bike shops (`02_Business_Model.md`'s Future Segments) is pulled forward, which is out of scope for this 12-month forecast.

---

# Part 4 — Review Plan Summary

| Review Point | Trigger | What Gets Re-Validated |
|---|---|---|
| After customer discovery interviews (Phase 1 in `10_Roadmap.md` / `15_Customer_Discovery.md`) | 15-20 interviews completed | Willingness to pay, price sensitivity, most valuable module — replaces Part 2's assumptions with real data |
| After pilot recruitment | 3-5 pilot businesses signed | Actual pilot pricing decision (reduced/free vs. full price), onboarding effort, time-to-first-value |
| After pilot phase (Gate C, `10_Roadmap.md`) | Pilots complete a full usage cycle | Real conversion rate from pilot to paying, real churn signal, real support cost per customer |
| At public launch (Phase 6) | Billing activated | First real MRR figure — replaces every number in Part 3's tables |
| Quarterly thereafter | Ongoing | Cost per customer (`08_Cost_Analysis.md`), gross margin, MRR growth rate, churn, against the scenarios above |

**The review discipline:** every number in Part 3 should be treated as disposable. The moment real pilot or launch data exists, this document should be updated to replace assumption with evidence, and the gap between the original scenario and the real outcome should itself be recorded — it's useful information about how well the founder's assumptions matched reality.

---

# Business Perspective

The business model is sound on paper and grounded in real competitor pricing, but the founder should not treat the revenue tables above as a business case for spending — they are a way to reason about scenarios, and the actual case for spending money (on tools, on marketing, on time) should wait for pilot evidence.

---

# Customer Perspective

Customers are not part of a forecast — they are part of a discovery process. The revenue numbers above exist for internal planning only and should never be presented to a prospective customer as if they were a track record.

---

# Technical Perspective

Nothing in this document requires new engineering work; it depends on the platform being able to report real usage, billing, and churn data once live, per the `ai_usage`, `subscriptions`, and `audit_events` tables described in `04_Database.md`, so that the Review Plan above can actually be executed with real data rather than estimates.

---

# Commercial Perspective

The most commercially important output of this document is not the revenue numbers — it's the explicit acknowledgment that demand is unvalidated. The founder's next commercial priority, ahead of any pricing or forecasting refinement, should be completing the interviews in `15_Customer_Discovery.md`.

---

# Current Decisions

* Adopt €80/month as the updated working reference price, superseding the €79 figure in `02_Business_Model.md` pending formal update (Proposed).
* Treat all revenue figures in this document as scenario planning, not forecasts to be relied upon for financial commitments (Accepted).
* Sequence paying revenue after pilot validation, not from month 1 (Accepted, consistent with `10_Roadmap.md`).

---

# Why This Decision?

**Decision:** Present revenue as a three-scenario range rather than a single-point forecast.

**Reason:** No sales data exists yet; a single-point forecast would imply false precision and could mislead the founder or an investor into treating an assumption as a fact. Financial and business planning of this kind should give the information needed to make an informed decision, not a confident recommendation the founder isn't in a position to rely on yet.

**Alternatives Considered:** A single "expected case" forecast was considered for simplicity, but rejected because it would obscure how sensitive the outcome is to unvalidated assumptions (pilot conversion rate, churn, launch timing).

**Future Review Criteria:** As defined in Part 4's Review Plan — replace each assumption with real data as each roadmap phase completes.

---

# Risks

* The biggest risk to this entire model is demand risk, not cost or pricing risk — this document cannot resolve that, only `15_Customer_Discovery.md` can.
* Founder time is the scarcest resource in the first 12 months; the forecast assumes founder-led acquisition with no paid marketing, which may not scale even in the optimistic scenario.
* The €79 vs. €80 pricing inconsistency across documents should be resolved promptly to avoid confusion in investor or planning conversations.

---

# Future Improvements

* Update `02_Business_Model.md`'s BD-001 and `11_ADRs.md` / `12_Architecture_Decision_Log.md` to reflect €80/month as the current working reference price, replacing €79.
* Once real interview data exists, replace Part 1's "Not validated" rows with actual findings.
* Once pilot billing begins (if pilots are charged), replace Part 3's Month 1-6 table with real figures.
* Add a simple churn and cohort-tracking approach once the first paying cohort exists, so month-12-and-beyond forecasting has a real basis.

---

# Questions Still Open

* Should pilot customers be charged at all, and if so, at what rate relative to €80/month?
* What conversion rate from pilot to paying customer is realistic — this document assumed roughly 25-60% across scenarios, which is itself unvalidated?
* At what point should the founder consider paid customer acquisition, given the assumption of zero paid marketing spend in the first 12 months?
* Should the €79/€80 pricing discrepancy be resolved now, or left until customer discovery gives a firmer number?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial draft; business model and pricing validated against `08_Cost_Analysis.md`; 6- and 12-month scenario-based revenue forecast added. |
