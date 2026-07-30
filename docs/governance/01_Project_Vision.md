# 01_Project_Vision.md

**Version:** 0.3 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---


# Document Contract

## Purpose

This document defines the long-term vision of the AI Operations Platform.

It explains why the company exists, the problems it aims to solve, why independent bike shops are the first target market, and how the company intends to create long-term value for customers.

Unlike the Company Constitution, this document is expected to evolve as assumptions are validated through customer interviews, product usage and market feedback.

---

## Audience

* Founder
* Future Employees
* Product Managers
* Software Engineers
* Investors
* Strategic Partners

---

## In Scope

* Market opportunity
* Business problem
* Vision
* Long-term strategy
* Customer value
* Competitive positioning
* Company assumptions
* Success definition

---

## Out of Scope

This document intentionally does **not** define:

* Product features
* Technical architecture
* Technology stack
* Database design
* Deployment
* Pricing
* Development roadmap

These topics are documented separately.

---

## Related Documents

* 00_Company_Constitution.md
* 02_Operational_Domains.md
* 03_System_Architecture.md
* 09_Business_Model.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

Small businesses generate valuable operational data every day.

Most of that data is never transformed into meaningful business decisions.

Instead, owners spend hours switching between spreadsheets, point-of-sale systems, supplier portals, invoices and workshop notes to understand what is happening inside their business.

AI Operations Platform exists to change that.

Our mission is not to replace business owners with Artificial Intelligence.

Our mission is to help them make better operational decisions by combining Business Intelligence, Forecasting, Machine Learning and Artificial Intelligence into one explainable decision-support platform.

The first product built on this platform is **Bike Shop AI Copilot**, focused exclusively on helping independent bicycle retailers operate with the same level of intelligence typically available only to much larger organisations.

---

# Guiding Questions

Every strategic decision made by the company should answer these questions.

* Does this help business owners make better decisions?
* Does this solve a measurable business problem?
* Does this strengthen our long-term competitive advantage?
* Can this scale beyond one industry?
* Can this recommendation be clearly explained to the customer?

If the answer is **No**, we should challenge whether we are building the right solution.

---

# The Problem

Small businesses often make important operational decisions using fragmented information.

A typical owner may need to consult:

* Point-of-sale reports
* Excel spreadsheets
* Supplier catalogues
* Inventory reports
* Workshop notes
* Emails
* Invoices

before deciding:

* What should I order?
* Which products are underperforming?
* Why did profits change?
* Which repairs are most profitable?
* How much inventory should I keep?

The information exists.

The decisions are still difficult.

---

# Why Now?

Several trends have created an opportunity that did not exist a few years ago.

* Most small businesses already use digital point-of-sale systems.
* Cloud infrastructure has become affordable.
* Artificial Intelligence has become commercially accessible.
* Machine Learning tools have matured significantly.
* Business owners increasingly expect simple, intelligent software rather than static reports.

Enterprise-level operational intelligence is no longer limited to enterprise companies.

---

# Why Bike Shops?

Bike shops represent an ideal first vertical because they combine multiple operational challenges within a manageable business size.

Typical characteristics include:

* Retail sales
* Workshop operations
* Inventory management
* Supplier relationships
* Seasonal demand
* Multiple revenue streams
* High-value stock
* Small operational teams

These characteristics allow us to validate our platform in a real business environment before expanding into additional retail sectors.

Our long-term vision is broader than bike shops.

Our immediate focus is not.

---

# Target User

The platform is built for the independent shop **owner-operator**, not a data analyst and not an enterprise IT buyer.

Typical characteristics:

* Time-poor — runs the counter, the workshop, and the business simultaneously.
* Not a data specialist — will not clean spreadsheets, map columns, or learn a BI tool.
* Decision-driven, not curiosity-driven — wants "what should I do," not "what does this chart mean."
* Already paying for a POS/EPOS system and reluctant to replace it.
* Trusts explanations more than black-box scores.

This is the user every requirement in `10_Product_Requirements.md` is written for — most directly PR-1 (Onboarding) and PR-2 (Data Ingestion), where the no-import-template decision (PD-006) exists specifically because this user will not do data preparation work.

---

# Our Theory of the Business

Inspired by the management thinking of Peter Drucker, we recognise that every company is built on assumptions.

Rather than treating these assumptions as facts, we will continuously validate them through customer interviews, product usage and measurable outcomes.

Current assumptions include:

* Independent businesses already possess enough operational data to improve decision-making.
* Business owners prefer recommendations over dashboards.
* Customers will pay for measurable operational improvements.
* Explainable recommendations create greater trust than opaque AI responses.
* Industry-specific operational intelligence creates more value than generic AI assistants.
* Artificial Intelligence should communicate business insights rather than replace business logic.

As evidence grows, these assumptions may be refined or replaced.

---

# Current Reality

Today, many independent businesses operate reactively rather than proactively.

Operational data is spread across multiple systems.

Business owners spend valuable time collecting information instead of acting on it.

Important decisions often depend on:

* Experience
* Intuition
* Historical habits
* Manual analysis

rather than consistent, data-driven recommendations.

---

# Our Vision

We envision a future where every independent business has access to an AI Operations Platform that continuously analyses operations, identifies opportunities, predicts future outcomes and recommends the next best action.

Rather than becoming another dashboard, the platform becomes the operational intelligence layer of the business.

Business owners should begin their day by understanding:

* What changed yesterday.
* What requires attention today.
* What is likely to happen tomorrow.
* What actions should be prioritised next.

---

# Our Solution

AI Operations Platform combines:

* Business Intelligence
* Operational Analytics
* Forecasting
* Machine Learning
* Company Knowledge
* Artificial Intelligence

into a single decision-support platform.

Rather than simply presenting information, the platform explains what is happening, why it is happening and what actions should be considered next.

---

# Product Principles

These are product-level commitments that follow from the Company Constitution's principles, made specific enough to design and test against. Other governance documents (`03_System_Architecture.md`, `05_AI_Architecture.md`, `06_Database_Design.md`, `10_Product_Requirements.md`) cite these by name.

* **Never Hallucinate Numbers** — every figure shown to a customer must trace to stored data or a deterministic calculation. AI-generated text must never contain a number that was not present in the structured input it was given (Constitution Principle 3; enforced by PR-5.3 in `10_Product_Requirements.md`).
* **Action-Oriented Analytics** — every module surfaces a prioritised recommended action alongside a metric, not a metric alone (Constitution Principle 2).
* **AI-Agnostic** — no product feature may depend on a single AI vendor; all AI requests are routed through the internal AI Provider Gateway (Constitution Principle 6; implemented per `05_AI_Architecture.md`).
* **Industry-Flexible Core** — the canonical data model and calculation engine must generalise across verticals. Bike-shop-specific terminology and rules live only in the business-template layer, never in shared core tables (Constitution Principle 8; implemented per `06_Database_Design.md`).
* **EU Infrastructure Where Practical / Privacy by Design** — prefer EU-region hosting and EU-compliant data processing, and collect only the customer data a feature actually needs (Constitution Principle 7).
* **Low-Friction Use** — the customer reaches value with minimal setup effort. The customer is never asked to reformat, template, or pre-clean their data before uploading it (PD-006, Accepted — see `10_Product_Requirements.md`, PR-2. This principle previously proposed a downloadable import template; that approach was superseded by PD-006 and this section now reflects the current, accepted requirement).

---

# Why AI Alone Is Not Enough

Artificial Intelligence can answer questions.

Businesses require systems that improve decisions.

A successful recommendation depends on:

* Business logic
* Historical data
* Forecasting models
* Operational rules
* Company-specific knowledge
* Human context

Artificial Intelligence becomes the communication layer—not the decision engine itself.

This philosophy allows us to build software that is more trustworthy, more explainable and significantly more cost-effective than AI-first solutions.

---

# Competitive Advantage

Our competitive advantage is not a Large Language Model.

It is the combination of:

* Business Intelligence
* Industry-specific operational knowledge
* Deterministic business logic
* Forecasting
* Machine Learning
* Explainable Artificial Intelligence
* Customer-specific operational memory

Together, these capabilities create a platform that is considerably harder to replicate than a simple AI chatbot.

---

# Customer Promise

We promise to provide recommendations that are:

* Transparent
* Explainable
* Actionable
* Business-focused

We will help customers make better operational decisions.

We will never ask them to trust recommendations they cannot understand.

---

# Definition of Success

We succeed when independent business owners spend less time searching for answers and more time making confident operational decisions.

If our customers consistently make better decisions because of our platform, the company will achieve its mission.

---

# Business Perspective

Our objective is to build a scalable Software-as-a-Service company by solving measurable operational problems for independent businesses.

Bike shops are our first market because they provide an ideal environment to validate the platform before expanding into additional industries.

---

# Customer Perspective

Customers should feel they have hired an experienced business analyst rather than purchased another software application.

The platform should become a trusted advisor that helps them improve profitability, efficiency and operational confidence.

---

# Technical Perspective

The platform will combine deterministic calculations, machine learning models and AI-powered communication.

Business recommendations will be generated through trusted business logic.

Artificial Intelligence will explain, summarise and communicate those recommendations in natural language.

---

# Commercial Perspective

Our long-term opportunity is to build a reusable operational intelligence platform that can support multiple retail industries while maintaining industry-specific expertise through configurable business rules.

This creates a scalable business model without requiring the core platform to be rebuilt for each new market.

---

# Current Decisions

* Independent bike shops are our first commercial vertical.
* The company is building a reusable AI Operations Platform.
* AI will enhance decision-making rather than replace business logic.
* The platform will follow an AI-agnostic architecture.
* Every recommendation should make the customer's business better.

---

# Why These Decisions?

These decisions maximise long-term scalability while maintaining a focused go-to-market strategy.

Rather than attempting to serve every industry immediately, we will earn expertise in one market before expanding into others using the same underlying platform.

---

# Risks & Assumptions

Key risks include:

* Customers may have poor-quality operational data.
* Small businesses may initially distrust AI recommendations.
* Existing workflows may be difficult to change.
* Customers may underestimate the financial value of better decisions.

Our strategy is to reduce these risks through explainability, measurable ROI, customer collaboration and iterative product development.

---

# Questions Still Open

* Should the accepted €80/month price later include annual-billing discounts or additional tiers?
* Which customer segment should we target first within the bike shop market?
* What measurable ROI should every customer expect within their first year?
* What customer success metrics will determine product-market fit?

---

# Revision History

| Version | Date | Changes                       |
| ------- | ---- | ----------------------------- |
| 0.1     | TBD  | Initial project vision draft. |
| 0.2     | 30/07/2026 | Replaced the unresolved pricing-strategy question with future packaging options around the accepted €80/month price. |
| 0.3     | 30/07/2026 | Added "Target User" and "Product Principles" sections (Never Hallucinate Numbers, Action-Oriented Analytics, AI-Agnostic, Industry-Flexible Core, EU Infrastructure/Privacy by Design, Low-Friction Use) so the principles already cited by name in `03_System_Architecture.md`, `05_AI_Architecture.md`, `06_Database_Design.md`, and `10_Product_Requirements.md` are actually defined here; confirmed the import-template guidance is superseded by PD-006; standardised the header to the plain `**Field:** Value` format used by every other governance document (was previously a table); synced version header with revision history. |

