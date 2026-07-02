# 🚲 Bike Shop AI Copilot

> **An AI-powered business intelligence platform that helps independent bike shops make better operational decisions through forecasting, analytics, and intelligent recommendations.**

---

# Vision

Bike Shop AI Copilot is a Software-as-a-Service (SaaS) platform designed specifically for independent bicycle retailers.

Instead of replacing business owners, the platform acts as an **AI Business Analyst**, helping them understand their business, optimize inventory, reduce dead stock, improve purchasing decisions, and answer operational questions using a combination of business intelligence, machine learning, and Large Language Models (LLMs).

The goal is simple:

> **Help small bike shops make enterprise-level decisions without enterprise-level software.**

---

# The Problem

Many independent bike shops rely on intuition, spreadsheets, and manual reports to make important business decisions.

Common challenges include:

* Overstocking products that rarely sell
* Running out of high-demand products
* Difficulty understanding why profits fluctuate
* Time-consuming inventory analysis
* Staff searching through warranty or return policy documents
* Lack of demand forecasting
* Limited access to business intelligence tools

Large retail chains can afford expensive ERP and analytics systems.

Independent shops usually cannot.

Bike Shop AI Copilot aims to bridge that gap.

---

# Our Solution

Bike Shop AI Copilot combines traditional analytics, forecasting models, and AI into a single web platform.

The system analyses business data and produces actionable recommendations rather than simply displaying dashboards.

Examples include:

* Predicting which products should be reordered
* Detecting slow-moving inventory
* Explaining changes in profitability
* Answering questions about company policies
* Forecasting future demand
* Producing automated business reports
* Acting as an AI assistant that understands the business

---

# Core Principles

The platform is designed around several key principles:

## AI is used only when necessary

Business calculations should not rely on a Large Language Model.

Instead:

* SQL retrieves the data.
* Python performs calculations.
* Machine Learning predicts future trends.
* AI explains the results in natural language.

This significantly reduces operational costs while improving reliability.

---

## AI-Agnostic Architecture

The platform will not depend on a single AI provider.

Supported providers may include:

* OpenAI
* Google Gemini
* Anthropic
* Groq
* OpenRouter
* Future local models

This allows the system to switch providers as pricing and capabilities evolve.

---

## Explainable Recommendations

Every recommendation should include:

* What is happening
* Why it is happening
* How the recommendation was calculated
* Suggested next actions

The goal is to build trust rather than generate opaque AI responses.

---

# Planned Features

The initial release focuses on:

* Inventory Forecasting
* Reorder Recommendations
* Profit Variability Analysis
* Dead Stock Detection
* Warranty & Policy Assistant
* Business Knowledge Base (RAG)
* Business Memory
* AI Chat Assistant
* Weekly Automated Reports

Future versions may include:

* Dynamic pricing recommendations
* Employee scheduling
* Marketing insights
* Supplier benchmarking
* Customer segmentation
* Multi-branch analytics

---

# High-Level Architecture

```text
Customer
      │
      ▼
Web Application (Next.js)
      │
      ▼
FastAPI Backend
      │
 ┌───────────────┬────────────────┬────────────────┐
 │               │                │
 ▼               ▼                ▼
Calculation   ML Models      AI Services
Engine         Forecasting   (AI-Agnostic)
 │               │                │
 └───────────────┴────────────────┘
                │
                ▼
        PostgreSQL Database
                │
                ▼
      Reports & Recommendations
```

---

# Technology Stack

Planned technology stack:

* **Frontend:** Next.js
* **Backend:** FastAPI (Python)
* **Database:** PostgreSQL (Supabase)
* **Authentication:** Supabase Auth
* **Storage:** Supabase Storage
* **Hosting:** Render + Vercel
* **Payments:** Stripe
* **AI:** AI-agnostic architecture supporting multiple providers

---

# Repository Documentation

This repository is organised into dedicated design documents:

| File                                | Purpose                               |
| ----------------------------------- | ------------------------------------- |
| 01_Project_Vision.md                | Business vision and long-term goals   |
| 02_Features_Modules.md              | Functional modules and user features  |
| 03_System_Architecture.md           | Overall software architecture         |
| 04_Technology_Stack.md              | Technology decisions and alternatives |
| 05_Cost_Analysis.md                 | Infrastructure and operating costs    |
| 06_Business_Model.md                | Pricing, customers and revenue model  |
| 07_Deployment_Guide.md              | Deployment and infrastructure guide   |
| 08_Roadmap.md                       | Development roadmap                   |
| 09_Database_Design.md               | Database schema and data model        |
| 10_AI_Architecture.md               | AI strategy and calculation engine    |
| 11_Product_Requirements_Document.md | Detailed product specification        |

---

# Long-Term Vision

The first target market is independent bike shops.

Once the platform is validated, the same architecture can be adapted for other retail sectors with minimal changes, including:

* Outdoor equipment stores
* Sports retailers
* Cafés
* Bakeries
* Garden centres
* Hardware stores
* Pet stores
* Other independent retailers

The long-term objective is to create a scalable AI Operations Copilot platform that helps small and medium-sized businesses make better operational decisions through accessible, explainable, and affordable AI.

---

# Current Status

**Project Phase:** Planning & Architecture

Current focus:

* Define business requirements
* Design software architecture
* Select technology stack
* Build MVP
* Validate with independent bike shops

---

## License

This project is currently under active development.

License details will be added prior to the first public release.

