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

## Folders

| Folder | Purpose |
|---|---|
| `app/` | Next.js routes (App Router) |
| `components/` | Reusable UI components |
| `lib/api/` | Every backend call goes through here — no component calls `fetch` directly |
| `types/` | Shared TypeScript types, mirroring backend schemas |
