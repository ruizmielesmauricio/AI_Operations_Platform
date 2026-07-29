# 08_Cost_Analysis.md

**Version:** 0.1 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** TBD

---

# Document Contract

## Purpose

This document has two parts. First, it maps the competitive landscape in Ireland and internationally — what independent bike shops currently pay for software, and what that software does and does not do — so the company's positioning and pricing are grounded in evidence rather than assumption. Second, it estimates the platform's own operating cost per customer, based on the architecture and deployment model already defined in this repository.

Together, these two halves answer the question a founder must answer before committing to €80/month: *is there room for that price in the market, and does the business make money at it?*

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
* Estimated fixed and variable operating cost per customer
* Cost stages (prototype, pilot, early production)

---

## Out of Scope

This document intentionally does **not** define:

* Alternative pricing tiers, discounts, and future price changes (see `09_Business_Model.md`)
* Revenue forecasting (see `09_Business_Model.md`)
* Detailed infrastructure configuration (see `07_Deployment_Guide.md`)
* Cost-control engineering rules (see `07_Cost_Strategy.md`, detailed set)

---

## Related Documents

* 02_Business_Model.md
* 07_Cost_Strategy.md (detailed set)
* 07_Deployment_Guide.md
* 09_Business_Model.md
* 15_Customer_Discovery.md

---

# Executive Summary (TL;DR)

Independent bike shops in Ireland and internationally already pay for point-of-sale (POS) and EPOS software — typically €30–€340/month depending on sophistication — but that spend buys transaction processing and basic inventory reporting, not forecasting, profitability explanation, or AI-assisted decision support. General-purpose business intelligence tools (Databox, Grow.com, Klipfolio) fill part of that gap but are not built for retail/workshop operations and require the owner to do their own data modelling. Generic AI copilots (Microsoft 365 Copilot and similar) are not connected to the shop's structured business data at all.

This creates a real, evidenced gap: **nothing in the market combines industry-aware retail + workshop analytics with deterministic calculation and AI explanation, at a price an independent shop can justify.** At €80/month, we sit below premium POS tiers and mid-tier general BI tools, while offering something neither category currently provides.

On the cost side, estimated fixed infrastructure cost at pilot scale is low (roughly €60–€150/month total, not per customer), with AI cost as the main variable cost per customer — which is precisely why the AI provider routing strategy in `05_AI_Architecture.md` matters commercially, not just architecturally.

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

# Part 2 — Estimated Operating Cost

## Cost Categories

Per `07_Cost_Strategy.md`, cost is split into fixed infrastructure cost (largely independent of customer count at small scale) and variable cost per customer (mainly AI usage and storage).

## Estimated Fixed Monthly Cost (Pilot Stage, ~1-10 customers)

| Item | Estimated Monthly Cost (EUR) | Notes |
|---|---|---|
| VPS (Hetzner or similar) | €10-€25 | Hosts web, API, worker, reverse proxy |
| Neon (PostgreSQL, managed) | €0-€25 | Free/low tier likely sufficient at pilot scale |
| Cloudflare R2 (object storage) | €1-€5 | Temporary files only; low volume |
| Resend (transactional email) | €0-€20 | Free tier likely sufficient at pilot volume |
| Sentry (error tracking) | €0-€26 | Free/developer tier likely sufficient initially |
| Uptime Kuma | €0 | Self-hosted, no license cost |
| Plausible Analytics | €0-€9 | Small self-hosted or entry cloud tier |
| Domain + DNS | ~€1 (amortized) | ~€10-€15/year |
| **Estimated fixed total** | **~€15-€110/month** | Wide range reflects free-tier eligibility at pilot scale |

## Estimated Variable Cost Per Customer (Monthly)

| Item | Estimated Cost per Customer (EUR) | Notes |
|---|---|---|
| Stripe processing fees | ~1.5%-2.5% of subscription value + fixed fee | Applies only to paying customers; varies by card vs. SEPA |
| AI usage (via OpenRouter-routed models) | €0.50-€3.00 | Depends heavily on plan limits (`05_AI_Strategy.md` cost controls) and model routing decisions (`05_AI_Architecture.md`) |
| Incremental storage | <€0.50 | Uploads are temporary by default; normalized data is small relative to object storage |
| Incremental database load | <€1 | Shared Neon instance absorbs this at low customer counts |
| **Estimated variable total** | **~€2-€6 per paying customer, plus card/SEPA fees** | To be validated against real pilot usage |

## Estimated Gross Margin at €80/Month

Using the ranges above, at a small number of pilot customers:

```text
Revenue per customer:        EUR 80.00
Estimated Stripe fee:        ~EUR 1.50-2.50 (varies by payment method)
Estimated AI cost:           ~EUR 0.50-3.00
Estimated storage/DB cost:   ~EUR 1.00 (shared, allocated)
--------------------------------------------------
Estimated variable cost:     ~EUR 3.00-6.50 per customer
Estimated contribution:      ~EUR 73.50-77.00 per customer, before fixed cost allocation
```

Fixed costs (~€15-€110/month total) are shared across all customers, so gross margin improves sharply as customer count grows past pilot scale — this is a favourable cost structure for a subscription SaaS business, but it has not yet been validated against real usage data.

## Cost Stage Progression

* **Prototype (Phase 2):** Near-zero cost; free tiers, no production billing, single founder testing.
* **Pilot (Phase 3-4):** Costs as estimated above; 3-5 pilot businesses per `10_Roadmap.md`, likely at reduced or waived pricing during validation.
* **Early Production (Phase 6+):** Fixed costs may need to move off free tiers (Sentry, Resend, Neon) as usage grows; this is the point at which real cost-per-customer data should replace these estimates.

---

# Business Perspective

The competitive analysis confirms €80/month sits in a defensible price band — above basic Irish EPOS entry tiers but well below premium POS plans and mid-tier general BI tools — provided the product delivers what neither category currently offers: explainable, industry-aware analytics.

---

# Customer Perspective

A bike shop owner already paying for a POS system should be able to justify an additional €80/month specifically because it answers questions their POS cannot: why margin changed, what to reorder, and how the workshop is really performing — not because it replaces anything they already use.

---

# Technical Perspective

The variable cost structure (AI usage as the dominant variable cost) is precisely why the AI Provider Gateway and OpenRouter routing strategy in `05_AI_Architecture.md` are commercially load-bearing, not just an architectural nicety — controlling AI cost per request is what protects the gross margin estimated above.

---

# Commercial Perspective

At current estimates, gross margin per customer is high once past pilot scale, which supports the founder-led, low-fixed-cost model described in `07_Cost_Strategy.md`. The main commercial risk is not infrastructure cost — it is customer acquisition cost and willingness to pay, which this document cannot validate and which `15_Customer_Discovery.md` interviews must address directly.

---

# Current Decisions

* Set the current subscription price at €80/month per business (BD-005, Accepted).
* Treat AI usage as the primary variable cost to actively manage per customer (Accepted, consistent with `07_Cost_Strategy.md`).
* Treat this competitive analysis as based on public pricing pages, to be revisited after direct competitor trials and customer interviews (Accepted).

---

# Why This Decision?

**Decision:** Set the current subscription price at €80/month per business, positioned as a complement to (not a replacement for) the shop's existing POS/EPOS system.

**Reason:** Competitor pricing shows a real gap between basic EPOS reporting and expensive/generic BI tools that this price point sits inside, while the estimated cost structure supports healthy gross margin at that price.

**Alternatives Considered:** Pricing below €50/month to undercut basic EPOS tiers was considered, but rejected for now because it risks signalling "another cheap add-on" rather than a serious decision-support tool, and doesn't match the value described in `01_Product_Vision.md`. Pricing above €150/month (near premium POS tiers) was also considered and rejected as too high before the product's value is proven to a first paying cohort.

**Future Review Criteria:** €80/month remains the current price. Review future pricing, packaging, or discounts only when `15_Customer_Discovery.md` interviews provide willingness-to-pay evidence or real pilot costs materially change the unit economics.

---

# Risks

* Competitor pricing pages change frequently and may already be out of date by the time this is read; treat as directional, not exact.
* Actual AI cost per customer could exceed estimates if usage patterns (e.g., long conversational sessions) are heavier than assumed — mitigated by the usage controls and caching strategy in `05_AI_Strategy.md`.
* Owners may resist a second subscription regardless of price, if they don't yet trust AI-driven recommendations — this is a customer discovery risk, not a cost risk, and is tracked in `15_Customer_Discovery.md`.

---

# Future Improvements

* Replace estimated infrastructure and AI costs with real pilot-phase measurements once Phase 3/4 begins.
* Conduct direct trials of at least two or three competitor products (not just marketing pages) to validate the feature gap analysis first-hand.
* Track cost per customer as a live metric (per `07_Cost_Strategy.md`'s Cost Review Metrics) rather than relying on this document's estimates past the pilot stage.

---

# Questions Still Open

* What is real customer willingness to pay €80/month alongside an existing POS subscription?
* How much AI usage does a typical owner actually generate per month, and does it match the estimated €0.50-€3.00 range?
* Should pilot customers pay a reduced rate, or use the product free during validation, per `10_Roadmap.md`'s Phase 3/4 guidance?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial draft; competitive landscape and cost estimate based on public pricing research. |
| 0.2 | 30/07/2026 | Confirmed €80/month as the accepted current price and aligned pricing language with BD-005. |
