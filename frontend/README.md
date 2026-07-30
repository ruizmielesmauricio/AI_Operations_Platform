# Frontend — AI Operations Platform Web App

Next.js (App Router) + TypeScript.

## Local development (without Docker)

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

## Local development (with Docker)

From the repo root: `docker compose up` — see `../backend/README.md`.

## Auth setup (required to actually log in)

The app runs and builds without this — `/health` works, and `/login`/`/signup`/`/onboarding`
show a clear "not configured" message instead of crashing. To actually sign up and create a
business:

1. Create a free project at [supabase.com](https://supabase.com) (a couple of minutes, no card required).
2. Copy its Project URL and `anon` public key into `frontend/.env.local` (`NEXT_PUBLIC_SUPABASE_URL`,
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` — see `.env.example`).
3. Copy the project's JWT secret into `backend/.env` as `SUPABASE_JWT_SECRET` — this is what the
   API uses to verify the session token the frontend sends it (see `app/security/auth.py`).

## Folders

| Folder | Purpose |
|---|---|
| `app/` | Next.js routes (App Router) |
| `components/` | Reusable UI components |
| `lib/api/` | Every backend call goes through here — no component calls `fetch` directly |
| `lib/supabase/` | Supabase Auth client — identity only, per ADR-013 |
| `types/` | Shared TypeScript types, mirroring backend schemas |
