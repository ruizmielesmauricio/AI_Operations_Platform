# Backend — AI Operations Platform API

FastAPI application. See `docs/governance/03_System_Architecture.md` and
`docs/templates/GitHub Structure.md` for the intended folder structure and
CLAUDE.md for the non-negotiable rules each folder enforces.

## Local development (without Docker)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # point DATABASE_URL at a local Postgres
uvicorn app.main:app --reload
```

## Local development (with Docker — recommended, matches production shape)

From the repo root:

```bash
cp .env.example .env
docker compose up
```

This starts a local Postgres container, the API on `http://localhost:8000`,
and the frontend on `http://localhost:3000`.

## Tests

```bash
cd backend
pytest
```

## Folders

| Folder | Purpose |
|---|---|
| `app/api/` | Thin FastAPI routes — no business logic |
| `app/application/` | Orchestrates domain logic + repositories for a route |
| `app/domain/` | Deterministic business logic and formulas |
| `app/analytics/` | The calculation engine (Retail / Workshop / Financial) |
| `app/forecasting/` | Forecasting models (deferred past the skeleton) |
| `app/ai/` | The ONLY place an AI provider SDK may be imported |
| `app/imports/` | Upload, schema detection, mapping, normalisation |
| `app/templates/` | Business template definitions (bicycle_shop first) |
| `app/billing/` | Stripe integration (deferred past the skeleton) |
| `app/jobs/` | Background workers, scheduled reports |
| `app/security/` | Auth verification, tenant scoping |
| `app/models/` | SQLAlchemy models |
| `app/schemas/` | Pydantic request/response contracts |
| `app/repositories/` | All database queries live here |
| `migrations/` | Alembic migrations |
| `tests/unit/` | Formula and logic tests, no I/O |
| `tests/integration/` | Tests against a real database |
| `tests/tenant_isolation/` | Cross-tenant access must always fail |
