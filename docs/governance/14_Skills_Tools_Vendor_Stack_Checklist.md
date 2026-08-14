# 14_Skills_Tools_Vendor_Stack_Checklist.md

**Version:** 0.3 (Draft)
**Status:** Draft
**Phase:** Phase 1–2 (Documentation → Prototype)
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---

# Document Contract

## Purpose

This document is a practical checklist of the skills, tools, and vendor accounts needed to build the platform, organised by category. It translates the governance-level technology decisions in `04_Technology_Stack.md` and `12_Decision_Register.md` into concrete install steps and account setup, and separates that from competencies that require a person (accountant, solicitor) rather than a package.

## Audience

* Founder
* Engineering Team
* Future Employees

## In Scope

* Concrete tools, libraries, and install commands per technology category
* Financial/legal competencies that require a professional, not a package
* Claude Skills that can be built to encode this project's conventions

## Out of Scope

This document intentionally does **not** define:

* Why a technology category was chosen (see `04_Technology_Stack.md`)
* Architecture or data model (see `03_System_Architecture.md`, `06_Database_Design.md`)
* Delivery sequencing (see `11_Development_Roadmap.md`)

## Related Documents

* 03_System_Architecture.md
* 04_Technology_Stack.md
* 05_AI_Architecture.md
* 06_Database_Design.md
* 10_Product_Requirements.md
* 11_Development_Roadmap.md
* 12_Decision_Register.md

---

## How to read this document

"Skill" means two different things here, and they get installed differently:

1. **Technical/business competencies and tools** — things a person learns, or a package/service you configure. Most of this document is this kind.
2. **Claude Skills** — folders of instructions (`SKILL.md`) that make me (Claude) better at a specific recurring task inside this project (e.g. Claude Code). Covered at the end, with what I can actually build for you right now.

Nothing below is legal or financial advice — for company registration, tax, and contracts you need a solicitor/accountant in Ireland, not an AI.

---

## 1. Core Engineering

| Area | Why you need it | Concrete tool | How to add it |
|---|---|---|---|
| Database design & architecture | Multi-tenant schema, `business_id` scoping, migrations | PostgreSQL + ERD tool (dbdiagram.io, drawSQL, or `pgModeler`) | Design schema in dbdiagram.io first; implement via SQLAlchemy models + Alembic migrations in `backend/app/models` |
| PostgreSQL | System of record | `psql`, pgAdmin or TablePlus (GUI) | `brew install postgresql` (Mac) / Docker image `postgres:16` for local dev |
| Supabase Auth | Authentication only: signup, login, password resets, and sessions (ADR-013). Supabase Database and Supabase Storage are not used. | `supabase-py`, `@supabase/supabase-js` | `pip install supabase --break-system-packages`; `npm install @supabase/supabase-js` |
| Neon | Managed PostgreSQL and the system of record (ADR-013) | Neon CLI, `psycopg2`/`asyncpg` | Create project at neon.tech; connection string goes in `.env`, never in code |
| Cloudflare R2 | Temporary object/file storage for uploads and generated file objects—not the PostgreSQL database (ADR-017) | S3-compatible client such as `boto3` or AWS SDK for JavaScript | Configure an R2 bucket and S3-compatible credentials in environment secrets; delete uploaded source files after successful ingestion |
| Node.js | Runtime for Next.js frontend | Node 20 LTS via `nvm` | `nvm install --lts`; `npx create-next-app@latest` |
| Python | Backend, analytics, AI orchestration | Python 3.12, `venv` or `poetry` | `python -m venv .venv`; `pip install fastapi uvicorn sqlalchemy alembic pydantic --break-system-packages` |
| FastAPI | REST API layer | `fastapi`, `uvicorn` | Included above |
| SQLAlchemy + Alembic | ORM + migrations | `sqlalchemy`, `alembic` | `pip install sqlalchemy alembic` |
| Background jobs | Imports, forecasts, cleanup (must be idempotent) | Dramatiq or RQ (per ADR pending in `04_Technology_Stack.md`) | `pip install dramatiq[redis]` once Redis is justified |
| Testing | Business-critical calculation correctness | `pytest`, `pytest-asyncio`, Playwright (frontend e2e) | `pip install pytest pytest-asyncio`; `npm install -D @playwright/test` |

## 2. Data & Machine Learning

| Area | Why | Tool | Install |
|---|---|---|---|
| Forecasting (seasonal averages → exponential smoothing → ML) | Revenue/demand forecasts (10_Product_Requirements.md) | `statsmodels`, `pandas`, `numpy` | `pip install pandas numpy statsmodels scikit-learn` |
| Anomaly / classification | Return-rate spikes, findings engine | `scikit-learn`, `xgboost` (only when justified) | `pip install scikit-learn xgboost` |
| Data cleaning / normalization | Import pipeline | `pandas` | Included above |
| Model evaluation discipline | Prevent silent forecast drift | Fixed test-case suite + calculation versioning (already in your Dev Rules) | No install — a practice, not a package |

## 3. Payments & Billing

| Area | Why | Tool | Install |
|---|---|---|---|
| Stripe integration | Subscriptions, SEPA DD, webhooks | `stripe` (Python), `stripe` (Node) | `pip install stripe`; `npm install stripe` |
| Webhook testing | Local dev without hitting prod | Stripe CLI | `brew install stripe/stripe-cli/stripe`; `stripe listen --forward-to localhost:8000/billing/webhooks/stripe` — found live 14/08/2026: the route actually lives under the `/billing` prefix (`app/api/billing.py::webhook_router`) and always has, since the very first billing commit; this line previously said the bare `/webhooks/stripe` path, which 404s. Must be running continuously for any billing/employee-seat/branch-payment webhook to be received at all in local dev — nothing else keeps it alive. |

## 4. Financial & Legal (people, not packages)

These are competencies you need access to — via yourself learning, a part-time accountant, or a solicitor. There's no "install" step.

| Area | What's actually needed | Typical source |
|---|---|---|
| Financial modelling / unit economics | MRR, CAC, gross margin per customer (already scaffolded in 08_Cost_Analysis.md) | You + a spreadsheet/BI tool; a part-time bookkeeper later |
| Irish company registration | Company Registration Office (CRO) filing, director duties, share structure | Solicitor or formation agent (e.g. an Irish company formation service) |
| Tax & Revenue setup | VAT registration, Corporation Tax, payroll if hiring | Irish accountant (mention "Revenue Online Service" — ROS — but a professional should file it) |
| Contracts & Terms of Service | SaaS terms, DPA, refund policy | Solicitor, or a reviewed SaaS legal template as a starting draft |
| GDPR / data protection registration | Data controller obligations, DPIA if needed | Solicitor or GDPR consultant for review; you can draft the technical controls (below) |

## 5. Design (UI/UX)

| Area | Why | Tool | Install |
|---|---|---|---|
| UI/UX design | Consistent, trustworthy dashboard experience | Figma (design), Tailwind CSS (implementation) | Figma is web-based, free tier fine to start; `npm install -D tailwindcss postcss autoprefixer` |
| Component system | Avoid ad-hoc styling | shadcn/ui on top of Tailwind | `npx shadcn@latest init` |
| Charting | Dashboards (per ADR-010, browser-rendered) | Apache ECharts | `npm install echarts echarts-for-react` |
| HTML/CSS fundamentals | Underneath Tailwind, still needed for custom layout, email templates, print/export views | No install — core web skill; MDN docs as reference |
| Accessibility | Charts and forms usable by everyone | `axe-core` for automated checks | `npm install -D @axe-core/playwright` |

## 6. Email & Deliverability

| Area | Why | Tool | Install |
|---|---|---|---|
| Transactional email | Invitations, import results, alerts | Resend | `npm install resend` or `pip install resend` |
| Email validation | Prevent bounces/fraud at signup | Syntax + MX check (`email-validator` Python lib) plus Resend's own deliverability tooling | `pip install email-validator` |
| Deliverability / domain auth | Emails don't land in spam | SPF, DKIM, DMARC DNS records | Configured in your domain's DNS once, following Resend's setup docs |

## 7. Security & Compliance

| Area | Why | Tool/Practice | Install |
|---|---|---|---|
| Web app security fundamentals | Injection, auth, tenant isolation bugs are existential for a multi-tenant SaaS | OWASP Top 10 as a checklist | Free — OWASP Cheat Sheet Series (reference, not installed) |
| Dependency vulnerability scanning | Catch known CVEs in packages | GitHub Dependabot, `pip-audit` | Enable Dependabot in repo settings; `pip install pip-audit` |
| Secrets management | No secrets in source control (per 12_Decision_Register.md) | `.env` + GitHub Actions secrets, or a vault later | `.gitignore` your `.env`; use repo "Secrets" in GitHub settings |
| Error tracking | Catch production bugs without exposing customer data | Sentry | `pip install sentry-sdk`; `npm install @sentry/nextjs` |
| Row Level Security | Defense-in-depth for tenant isolation | Postgres native RLS policies | Written as SQL in migrations, no separate install |
| GDPR technical controls | Data minimization, deletion, audit trail | Retention jobs + audit_events table (already scoped in 06_Database_Design.md) | Implementation work, not a package |

---

## 8. Claude Skills — what I can actually build for you

This project already has these Anthropic-provided skills available: `docx`, `pdf`, `pptx`, `xlsx`, `frontend-design`, `product-self-knowledge`, plus meta-tools like `skill-creator`.

For a project like this, it's worth building a few **custom project-specific skills** so that future Claude Code / Claude sessions apply your conventions automatically instead of me re-deriving them each time. Good candidates:

1. **`bikeshop-schema`** — encodes your tenant model, naming conventions (`business_id` scoping), canonical entities, and import-provenance fields from `06_Database_Design.md`, so any future schema/migration work follows the same pattern automatically.
2. **`ai-gateway-conventions`** — encodes the structured-input/output contract from `05_AI_Architecture.md` (the JSON packet shape, prohibited AI uses, validation rules) so any AI feature I help build calls the gateway correctly and never free-hands a number.
3. **`adr-writer`** — encodes your ADR/BD/PD/ED template and status values from `12_Decision_Register.md`, so decision docs come out consistently formatted without you re-pasting the template each time.
4. **`ui-design-system`** — encodes your Tailwind/shadcn/ECharts choices and dashboard layout principles from `01_Project_Vision.md` and `10_Product_Requirements.md`, so generated frontend code matches your intended look rather than generic defaults.

**How to actually create these:** I'd use the `skill-creator` meta-skill to scaffold each one — it structures a `SKILL.md` with the right triggers and format. Once created, where they live depends on where you're working:

- **In Claude Code:** skills go in a `.claude/skills/` folder inside your repo (or a shared skills folder referenced in `CLAUDE.md`) — they're just files, so they commit to git like any other project file and every contributor gets them automatically.
- **In claude.ai / this chat interface:** custom skills can be uploaded as a skill package under your account/workspace's capability settings — check `claude.ai` settings for the current skills upload option, since this UI changes.

Say the word and I'll build the first one (I'd suggest starting with `bikeshop-schema` or `adr-writer`, since those save you the most repetitive re-explaining).

---

## Summary: what to actually do first

Given you're still in Phase 1–2 (documentation → prototype), the highest-leverage next steps are:
1. Set up local dev: Python venv, Node, Docker Postgres.
2. Stand up Supabase (auth) + Neon (db) accounts and wire a bare FastAPI + Next.js skeleton.
3. Get Figma + Tailwind + shadcn in place before writing dashboard code, so design isn't retrofitted.
4. Talk to an Irish accountant/solicitor *before* CRO registration — not urgent yet per your own roadmap (Phase 5), so don't let it block the prototype.
5. Let me build the `bikeshop-schema` and `adr-writer` Claude Skills so subsequent sessions stay consistent with this doc set.

---

# Revision History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-07-29 | Initial skills/tools checklist created. |
| 0.2 | 2026-07-30 | Removed Supabase Storage, confirmed Supabase Auth only, Neon PostgreSQL as the system of record, and Cloudflare R2 as object/file storage rather than a database. |
| 0.3 | 2026-07-30 | Renamed file from "14 — Skills, Tools & Vendor Stack Checklist.md" to `14_Skills_Tools_Vendor_Stack_Checklist.md` to match the repository's naming convention; added the missing Document Contract (Purpose/Audience/In Scope/Out of Scope/Related Documents) required by ED-003; fixed a stale `01_Product_Vision.md` filename reference. |
