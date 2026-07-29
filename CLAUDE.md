# AI Operations Platform

Multi-tenant SaaS: turns small-business operational data into decisions.
First vertical: independent bike shops (Ireland). Must stay industry-flexible.

## Core Rule
Business Logic First. Deterministic Python calculates. AI only explains.
AI must NEVER calculate, aggregate, validate, or invent a number.

## Stack
Next.js/TS · FastAPI/Python · PostgreSQL (Neon) · Supabase Auth (auth only)
Cloudflare R2 · Stripe · Resend · OpenRouter (behind AI gateway only)

## Non-Negotiables
- Every table tenant-scoped via business_id
- No provider SDK outside backend/app/ai/
- Route handlers thin; logic in domain/ or analytics/
- Imports must be transactional and idempotent
- No bicycle-specific assumptions in core services
- Tests required for every business formula

## Where things are
- Strategy docs: docs/governance/
- Technical docs: docs/technical/
- Decisions: docs/decisions/
- Calculation engine: backend/app/analytics/
- Business templates: backend/app/templates/

## Read before architecture/product decisions
docs/governance/00_Company_Constitution.md
docs/technical/06_Development_Rules.md

## Conventions
- UTC internally, business timezone in settings
- Decimal for money, never float
- Machine-readable error codes
- Record decisions as ADRs in docs/decisions/