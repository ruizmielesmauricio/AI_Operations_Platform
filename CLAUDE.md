# AI Operations Platform

Multi-tenant SaaS turning small-business ops data into decisions. First vertical: independent bike shops (Ireland) — core stays industry-flexible; no bicycle-specific logic outside business templates.

## Core Rule
Business Logic First: deterministic Python calculates, AI only explains. AI never calculates, aggregates, validates, or invents a number.

## Stack
Next.js/TS · FastAPI/Python · PostgreSQL (Neon) · Supabase Auth (auth only) · Cloudflare R2 · Stripe · Resend · OpenRouter (behind AI gateway only)

## Non-Negotiables
- Tenant-scope every table via `business_id`
- No provider SDK outside `backend/app/ai/`
- Thin route handlers; logic in `domain/` or `analytics/`
- Imports transactional and idempotent
- No bicycle-specific assumptions in core services
- Tests required for every business formula

## File map
Strategy `docs/governance/` · Technical `docs/technical/` · Decisions `docs/decisions/` · Calc engine `backend/app/analytics/` · Templates `backend/app/templates/`

## Before architecture/product decisions, read
`docs/governance/00_Company_Constitution.md`
`docs/technical/06_Development_Rules.md` *(not yet written — `docs/technical/` is currently empty; skip until created)*

## Conventions
UTC internally, business timezone in settings · Decimal for money, never float · machine-readable error codes · record decisions as ADRs in `docs/decisions/`
