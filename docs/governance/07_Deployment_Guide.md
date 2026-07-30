# 07_Deployment_Guide.md

**Version:** 0.3 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 30/07/2026

---

# Document Contract

## Purpose

This document explains, explicitly and end-to-end, how the platform is deployed: which external tools and services are used, what each one is responsible for, and how they connect to every other part of the system. It is written so that a single founder can deploy, operate, and troubleshoot the entire system without needing to hold the full picture in their head.

It complements — rather than repeats — `03_System_Architecture.md` (system design) and `04_Technology_Stack.md` (tool selection rationale). This document answers the operational question: *given the architecture and the chosen stack, how does it actually get deployed and stay running?*

---

## Audience

* Founder
* Engineering Team
* Future Employees
* Investors (for operational due diligence)

---

## In Scope

* Every external tool/service used in deployment, and its exact responsibility
* How each service connects to every other component
* Environments (local, staging, production)
* CI/CD pipeline
* Secrets and environment variable management
* Domains, DNS, and TLS
* Backup and disaster recovery
* Monitoring and alerting
* Deployment sequence, step by step

---

## Out of Scope

This document intentionally does **not** define:

* Why each tool was chosen over alternatives (see `04_Technology_Stack.md`)
* Database schema (see `06_Database_Design.md`)
* Application-level business logic
* Pricing or cost rationale (see `08_Cost_Analysis.md`)

---

## Related Documents

* 03_System_Architecture.md
* 04_Technology_Stack.md
* 05_AI_Architecture.md
* 08_Cost_Analysis.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

The platform runs as a small number of containerized services (web app, API, background worker) deployed to a low-cost VPS, backed by managed external services for everything that shouldn't be self-hosted by a solo founder: database (Neon), authentication (Supabase Auth), object storage (Cloudflare R2), billing (Stripe), transactional email (Resend), AI routing (OpenRouter), source control and CI/CD (GitHub/GitHub Actions), error tracking (Sentry), uptime monitoring (Uptime Kuma), and privacy-friendly website analytics (Plausible).

Every external service sits behind a narrow, replaceable boundary in the application code, and every deployment goes through the same path: GitHub → GitHub Actions (tests, build) → container registry → VPS (via Coolify or direct Docker Compose) → health check → live.

---

# Full Connection Map

```text
                              +-----------------------+
                              |         User           |
                              +-----------+-------------+
                                          |  HTTPS
                                          v
                           +---------------------------+
                           |  Reverse Proxy / TLS        |  (Caddy/Traefik via Coolify)
                           +-------------+---------------+
                    +--------------------+--------------------+
                    v                    v                     v
          +-------------------+ +----------------+   +----------------------+
          |  Next.js Web App   | |  FastAPI API   |   |  Background Worker    |
          +---------+-----------+ +-------+--------+   +-----------+------------+
                    |                     |                        |
        Supabase Auth (session)           |                        |
                    |                     |                        |
                    +---------------------+------------------------+
                                          |
              +----------------------------+------------------------------+
              v                            v                               v
      +----------------+        +---------------------------+     +----------------+
      |  PostgreSQL      |        |  Cloudflare R2              |     |  Redis (opt.)  |
      |  (Neon)          |        |  (temp uploads, exports,    |     |  queue/cache   |
      +----------------+        |   customer assets)          |     +----------------+
                                 +---------------------------+
                                          |
              +----------------------------+------------------------------+
              v                            v                               v
      +----------------+        +---------------------------+     +----------------+
      |  Stripe          |        |  Resend                     |     |  OpenRouter    |
      |  (billing)       |        |  (transactional email)      |     |  (AI routing)  |
      +----------------+        +---------------------------+     +----------------+

      +-----------------------------------------------------------------------+
      |  Observability layer: Sentry (errors) - Uptime Kuma (uptime) -         |
      |  Plausible (public site analytics) - GitHub Actions (CI/CD)            |
      +-----------------------------------------------------------------------+
```

---

# External Tools and Their Exact Responsibility

## GitHub

**Role:** Source of truth for all code, infrastructure config, and documentation.

**How it connects:** Every push or pull request to the main branch triggers GitHub Actions. Nothing is deployed that hasn't passed through a pull request and the CI pipeline.

## GitHub Actions

**Role:** CI/CD — tests, linting, type checks, security checks, container builds, and deployment triggering.

**How it connects:**

```text
Push to main
  -> run backend tests (pytest)
  -> run frontend tests/typecheck (tsc, lint)
  -> build Docker images (web, api, worker)
  -> push images to container registry (GitHub Container Registry)
  -> trigger deployment (SSH/webhook to VPS, or Coolify deploy hook)
  -> post-deploy health check
```

Deployment must stop automatically if any prior step fails (per `12_Decision_Register.md`).

## Docker / Docker Compose

**Role:** Packages the web app, API, and worker as reproducible containers, both locally and in production.

**How it connects:** The same `docker-compose.yml` structure is used in local development (with a local Postgres container) and adapted for production (pointing at Neon instead of a local database). This keeps local and production environments structurally identical.

## Coolify (optional, self-hosted)

**Role:** Deployment manager sitting on top of Docker on the VPS — handles container orchestration, environment variables, domain/TLS configuration, and deployment triggers, without requiring Kubernetes.

**How it connects:** GitHub Actions calls a Coolify deploy webhook after a successful build. Coolify pulls the new container images and performs a rolling restart of the web, API, and worker services.

**If not used:** The same result is achieved with a simpler SSH-based `docker compose pull && docker compose up -d` deployment script triggered by GitHub Actions.

## Low-Cost VPS (e.g., Hetzner)

**Role:** Hosts the Next.js web app, FastAPI API, background worker, reverse proxy, and (if used) Redis.

**How it connects:** Receives all inbound HTTPS traffic through the reverse proxy, which routes requests to the correct container by hostname/path. It does not host the database in production — PostgreSQL is hosted separately via Neon for reliability and backup guarantees.

## Neon (PostgreSQL)

**Role:** Primary system of record — the single source of truth for all tenant data, imports, metrics, forecasts, billing state, and audit logs (per `06_Database_Design.md`).

**How it connects:** Both the FastAPI API and the background worker connect directly to Neon over an encrypted connection, using pooled connections. Neither the web app nor the browser ever connects to Neon directly.

**Why hosted separately from the VPS:** Managed backups, point-in-time recovery, and branching for development are handled by Neon rather than the founder manually managing database backups on a VPS (ADR-013 in `12_Decision_Register.md`).

## Supabase Auth

**Role:** Authentication only — issues and manages user sessions.

**How it connects:** The Next.js web app initiates authentication via Supabase Auth. The resulting session token is sent with every request to the FastAPI API, which verifies it before resolving business membership and permissions. Supabase's database and storage products are explicitly **not** used — only its Auth product — to keep authentication decoupled from the data layer (ADR-013).

## Cloudflare R2

**Role:** Temporary object storage for uploads, generated reports/exports, and customer assets such as logos.

**How it connects:**

```text
Browser requests an upload session
  -> FastAPI API creates a signed upload URL
  -> Browser uploads the file directly to R2 (not through the API)
  -> Background worker reads the object from R2 for parsing/validation
  -> Temporary file deleted from R2 after successful import (per retention rules in 06_Database_Design.md)
```

## Stripe

**Role:** Subscription billing, checkout, invoicing, and payment method management (cards and SEPA Direct Debit).

**How it connects:**

```text
User selects a plan in the web app
  -> FastAPI API creates a Stripe Checkout Session
  -> User completes payment on Stripe-hosted checkout
  -> Stripe sends a signed webhook to the FastAPI API
  -> API verifies the webhook signature
  -> API updates the local billing state in PostgreSQL
  -> Application access follows the locally stored subscription state
```

Paid access is never granted based solely on the browser redirect back from Checkout — only the verified webhook updates billing state (per `04_Technology_Stack.md`).

## Resend

**Role:** Transactional email — invitations, import completion/failure notices, alerts, and billing notices. Scheduled weekly/monthly performance reports (PR-8 in `10_Product_Requirements.md`, PD-007/ADR-019) are **not** sent through Resend — they are delivered in-app only; see "Scheduled Reporting Operations" below.

**How it connects:** The FastAPI API or background worker constructs the email request and calls Resend's API. Non-urgent email is sent by the worker rather than blocking a web request.

## OpenRouter

**Role:** AI model routing layer behind the internal AI Provider Gateway (see `05_AI_Architecture.md`), selecting a cost-effective, EU-compliant model above an approved quality threshold for each AI request.

**How it connects:** Only the FastAPI API's AI Provider Gateway module ever calls OpenRouter. No other component (web app, worker business logic, dashboards) references it directly. Structured, minimized context (metrics and findings, never raw customer data) is sent per `05_AI_Architecture.md`'s Data Minimization rules.

## Redis (optional)

**Role:** Queue broker for the background worker, caching, rate limiting, and short-lived locks — introduced only once actually needed (per `03_System_Architecture.md`).

**How it connects:** If used, both the FastAPI API (to enqueue jobs) and the background worker (to consume jobs) connect to the same Redis instance, hosted on the VPS or as a small managed add-on.

## Sentry

**Role:** Error tracking and performance monitoring across the web app, API, and worker.

**How it connects:** Each service reports unhandled exceptions and performance traces to Sentry. Sensitive customer content is never sent (per `12_Decision_Register.md`'s logging rules).

## Uptime Kuma

**Role:** Basic uptime and endpoint monitoring for the public website, web app, and API.

**How it connects:** Runs as its own lightweight container (on the same VPS initially, or ideally on independent infrastructure) and polls health-check endpoints on a schedule, alerting the founder (via email or messaging webhook) on failure.

## Plausible Analytics

**Role:** Privacy-friendly analytics for the **public marketing website only** — never for tracking activity inside authenticated customer dashboards.

**How it connects:** A lightweight script embedded only on public website pages, reporting to a self-hosted or managed Plausible instance.

---

# Environments

| Environment | Purpose | Database | Notes |
|---|---|---|---|
| Local | Founder development | Local PostgreSQL container | Docker Compose mirrors production structure |
| Staging | Pre-production validation | Separate Neon branch/project | Used to test migrations and imports safely before production |
| Production | Live customer data | Neon production database | Only environment connected to production Stripe/Resend/OpenRouter keys |

Neon's branching capability is specifically useful here: a staging branch can be created from production data (masked, per `06_Database_Design.md`'s security rules) to test risky migrations without touching live data.

---

# Secrets and Environment Variable Management

* No secrets are committed to source control (per `12_Decision_Register.md`).
* Environment variables (database connection strings, Stripe keys, Resend API key, OpenRouter API key, Supabase Auth keys) are stored in Coolify's environment configuration (or GitHub Actions Secrets + a VPS-side `.env` file if Coolify is not used).
* Separate keys are used per environment — staging never uses production Stripe or OpenRouter credentials.

---

# Domains, DNS, and TLS

* A single primary domain serves both the public marketing site and the authenticated application, differentiated by path or subdomain (e.g., `app.` subdomain for the authenticated product).
* TLS certificates are managed automatically by the reverse proxy (Caddy/Traefik via Coolify), which handles renewal without manual intervention.
* DNS is managed through the domain registrar or Cloudflare, which can also provide basic DDoS protection in front of the VPS.

---

# Deployment Sequence (Step by Step)

```text
1. Developer opens a pull request against main.
2. GitHub Actions runs tests, linting, and type checks.
3. On merge to main, GitHub Actions builds Docker images for web, API, and worker.
4. Images are pushed to GitHub Container Registry.
5. GitHub Actions triggers deployment (Coolify webhook or SSH script).
6. The VPS pulls the new images and performs a rolling restart.
7. A post-deploy health check confirms the API and web app respond correctly.
8. If the health check fails, the previous container version is kept running (no forced cutover).
9. Sentry and Uptime Kuma continue monitoring the new deployment.
```

---

# Backup and Disaster Recovery

* **Database:** Automated backups and point-in-time recovery handled by Neon; backup restoration is tested periodically, not assumed to work (per `06_Database_Design.md`'s security rules).
* **Object storage:** R2 holds only temporary files by default, so backup priority is low; retained files (if a customer enables retention) follow R2's own durability guarantees.
* **Application state:** Stateless containers (web, API, worker) require no backup — they can be rebuilt from the last known-good container image at any time.
* **Configuration:** Infrastructure and environment configuration is documented in this repository and Coolify's own configuration export, so the deployment can be reconstructed on a new VPS if needed.

---

# Business Perspective

Every external service in this document was chosen so a solo founder can operate the whole system without a dedicated DevOps hire — managed services absorb the operational burden (backups, TLS renewal, uptime) that would otherwise require constant manual attention.

---

# Customer Perspective

Customers experience a fast, reliable, EU-appropriate service. They do not need to know that six or seven different vendors are involved behind the scenes — only that uploads work, dashboards load, and billing is handled securely.

---

# Technical Perspective

Because every external service sits behind a narrow application-level boundary (repository, gateway, adapter), any single service in this document can be replaced without a full rewrite — this deployment guide describes the *current* choices, not permanent commitments.

---

# Commercial Perspective

This deployment model keeps fixed monthly infrastructure cost low at the prototype and pilot stages (see `08_Cost_Analysis.md` for the actual numbers), while still meeting the reliability and compliance bar customers will expect from a paid business tool.

---

# Current Decisions

* Deploy via Docker containers to a low-cost VPS, optionally managed through Coolify (Accepted, per `04_Technology_Stack.md`).
* Use GitHub Actions for CI/CD, with deployment blocked on test failure (Accepted, per `12_Decision_Register.md`).
* Host PostgreSQL on Neon rather than self-managed on the VPS (Accepted — ADR-013).
* Use Supabase strictly for Auth, not database or storage (Accepted — ADR-013).
* Avoid AWS-specific services and Kubernetes at this stage (Accepted — ADR-009).

---

# Why This Decision?

**Decision:** Combine a low-cost self-hosted VPS for compute with managed external services for anything stateful or security-critical (database, auth, storage, billing).

**Reason:** This balances cost control against operational risk — the founder self-hosts the cheap, stateless, easily-rebuilt parts (containers) and pays for managed reliability only where mistakes would be costly (data loss, billing errors, security incidents).

**Alternatives Considered:** Fully managed application hosting (Render, Railway, Fly.io) was considered for simplicity, and remains a valid fallback per `04_Technology_Stack.md` if VPS operation becomes too time-consuming for the founder to sustain alongside everything else.

**Future Review Criteria:** Revisit if VPS operational overhead becomes a measurable time cost, or if a real outage reveals a gap in this deployment model.

---

# Risks

* A solo founder operating a VPS directly introduces key-person operational risk. Mitigation: Coolify and documented configuration make the deployment reconstructable by someone else if needed.
* Multiple external vendors (eight-plus services) increase the number of things that can fail independently. Mitigation: Uptime Kuma and Sentry provide visibility, and every service sits behind a replaceable boundary.
* Manual DNS/TLS misconfiguration could cause downtime. Mitigation: automated certificate renewal via the reverse proxy reduces manual intervention.

---

# Future Improvements

* Move to a managed application host (Render/Railway/Fly.io) if VPS management becomes an operational burden, per the Scaling Path in `03_System_Architecture.md`.
* Introduce a staging Neon branch workflow formally into the CI/CD pipeline once migrations become riskier (multiple business templates, more customers).
* Add a second, independent uptime monitor outside the VPS itself, since a monitor co-located with the monitored service cannot detect a full VPS outage.

---

# Scheduled Reporting Operations

A timezone-aware scheduler dispatches separate weekly and monthly report jobs:

* Weekly: Monday at 08:00 in the customer's configured timezone.
* Monthly: first calendar day at 08:00 in the customer's configured timezone.
* A date collision does not merge the jobs; each produces its own report and in-app notification.

The worker calculates and renders the reusable in-app template from Neon data without using AI. Normal scheduled reports do not use Resend and do not create files in R2. PDF or Word is generated only after an explicit customer export request; any generated export follows the platform's temporary-file controls.

Reliability controls:

1. Use a unique key of tenant, report type, and reporting period.
2. Retry transient generation failures with bounded backoff.
3. Run an independent reconciliation job after the scheduled window to detect missing reports and force regeneration.
4. Alert the operator if the forced recovery also fails.
5. Record job attempts, report status, notification status, timestamps, and failure reasons in Neon.
6. Expire the customer-facing report after seven days and show the expiry date in its notification; retain only the minimum audit record required for operations and governance.

Deployment health checks must cover the scheduler, worker queue, recovery job, notification creation, expiry process, and on-demand export path.

---

# Questions Still Open

* Should staging environment costs be absorbed now, or only introduced once the pilot phase begins (Phase 3/4 in `11_Development_Roadmap.md`)?
* At what customer count does self-hosting on a VPS stop being the right tradeoff versus a managed application host?
* Should Redis be introduced now, or deferred until the background job architecture actually requires it?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial draft; full external-service connection map and deployment sequence documented. |
| 0.2 | 30/07/2026 | Clarified the Resend section to reference the PR-8/PD-007 weekly (Monday) and monthly (1st-of-month) scheduled report requirement; removed a duplicate `04_Technology_Stack.md` Related Document entry. |
| 0.3 | 30/07/2026 | Corrected the Resend section, which had incorrectly stated that scheduled reports are emailed — reports are in-app only (PD-007/ADR-019) and now cross-reference the "Scheduled Reporting Operations" section, which was already correct. |
