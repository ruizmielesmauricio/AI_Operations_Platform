# Project Instructions — Multi-Business Analytics SaaS

## Product purpose

Build a low-cost, secure, modular SaaS that helps small and medium-sized businesses make enterprise-quality decisions from their operational data.

Bike shops are the initial validation market, not the permanent product domain. Do not hard-code the platform core around bicycles, repairs, retail, or any single industry. Implement business-specific capabilities as optional modules over a shared platform.

## Product principles

1. Business logic first.
2. Deterministic code is authoritative for financial and operational metrics.
3. AI may explain, summarise, classify, or support decisions, but must not silently invent or become the source of truth for authoritative values.
4. Multi-tenant security and privacy are foundational.
5. Prefer simple, reversible, low-cost architecture until measured scale requires more.
6. Accessibility, usability, reliability, and clear explanations are product requirements.
7. Never sacrifice data integrity or tenant isolation for development speed.

## Architecture direction

- PostgreSQL is the source of truth.
- Database design should remain portable where practical.
- Supabase and Neon provider-specific behaviour must be isolated in adapters/migrations.
- The tenant entity is `organisation`.
- Users may belong to multiple organisations through explicit memberships.
- Use platform core, shared business primitives, optional domain modules, analytics, and provider adapters.
- Use version-controlled migrations.
- Use server-side authorization for protected actions.
- Use object storage for files, not database blobs, unless explicitly justified.
- Use background jobs for long-running imports, calculations, reports, and retriable integrations.
- Use provider interfaces for AI, email, storage, payments, and database-specific capabilities.

## Expected repository behaviour

Before editing:
- inspect existing code, tests, architecture docs, and ADRs;
- identify conflicts and assumptions;
- propose consequential architecture decisions before implementing them.

For every implementation:
- validate external inputs;
- enforce tenant authorization;
- define failure and recovery behaviour;
- add tests;
- update docs;
- run relevant checks;
- report evidence honestly.

## Security

Never commit or expose `.env` files, API keys, service-role keys, database URLs, Stripe secrets, webhook secrets, personal data, customer uploads, or production credentials.

Treat these as release blockers:
- cross-tenant access;
- authentication or authorization bypass;
- privilege escalation;
- payment manipulation;
- destructive migration without recovery;
- exposed secrets;
- unauthorised personal-data disclosure.

## Financial integrity

- Use decimal-safe arithmetic and `numeric` database types for money.
- Store currencies explicitly.
- Preserve transaction-time prices, taxes, discounts, and quantities.
- Separate cash, invoices, recognised revenue, and forecasts.
- Make formulas and assumptions inspectable.

## Workflow

Use the most relevant project Skill under `.claude/skills/`. For major changes, use a reviewer subagent from `.claude/agents/` after implementation.

Do not make production changes, deploy, submit legal filings, send emails, charge customers, or modify remote infrastructure unless explicitly instructed and the action has been reviewed.
