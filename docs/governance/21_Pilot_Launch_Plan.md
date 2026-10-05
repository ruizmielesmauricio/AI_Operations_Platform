# 21_Pilot_Launch_Plan.md

**Status:** Living document — updated as items complete
**Created:** 06/10/2026
**Owner:** Founder
**Related:** `11_Development_Roadmap.md`, `07_Deployment_Guide.md`, `08_Cost_Analysis.md`, `12_Decision_Register.md` (PD-011, PD-012), `17_Open_Questions.md`

---

# Goal and sequence (decided 06/10/2026)

Two clients interviewed have said the service is usable and that they would buy it. They become the **two pilot testers**. The sequence the founder set:

1. **Make the SaaS fully functional (target 100%)** — everything except GDPR/legal, which waits for the founder's legal/compliance session.
2. **Buy the domain** — only after the ORLA name is cleared (Q-001, Q-043).
3. **Build the public site** (what ORLA is, request access).
4. **Deploy the SaaS** as a normal hosted site, free tiers wherever possible.
5. **Testers use it** on complimentary accounts; their feedback drives fixes.
6. **Once the founder is 100% happy**, the two testers sign up through Stripe and become the first paying customers.

Principle: **use free tiers until a limit actually forces a paid plan** (see "Free-tier posture").

---

# A. Product readiness (before deployment)

| # | Item | Status |
|---|---|---|
| A1 | Undoing an import reverts the values it overwrote (prices, categories) | Done — v1.90 |
| A2 | Invoice screen warns about cost-price changes before confirming | Done — v1.90 |
| A3 | Complimentary pilot accounts (no Stripe), incl. staff and branches | Done — v1.91 |
| A4 | Plain-English audit of every screen/menu; central term list; "What's this?" hints | In progress — see `22_Plain_Language_Audit.md`; testers will add their own confusing terms |
| A5 | Ask ORLA question bank (~200 questions) + automated scorer; tune until consistently good; log unanswered questions during the pilot | Not started (needs the $10 OpenRouter credit to run at volume) |
| A6 | Invoice review: stacked layout for small screens; manual "add a line" for table-less invoices | Not started |
| A7 | First-run guidance and empty states (what a brand-new shop sees) | Not started — to be scoped in the audit |
| A8 | Pilot usage counters (report compute, exports, AI use per customer) to replace cost estimates with real numbers | Not started — meaningful only once testers use it |
| A9 | Switch Ask ORLA from the free model to a paid one (~$0.0002/question) | When the testers start — the free tier failed ~18% of calls in measurement |

Out of scope for now: legal documents, privacy notice, retention policy, Stripe live mode (waiting on the legal session and company setup); prescriptions (PD-011); OCR (PD-012).

---

# B. Deployment checklist (do after the domain and public site)

Everything free until it has to be paid. **You** = founder creates the account or enters payment/identity details; **Me** = built and configured by the assistant.

| Item | You | Me |
|---|---|---|
| Domain (after ORLA is cleared) + DNS | Buy; point DNS | Config values, redirects |
| Hosting for the web app and API | Create accounts (managed host preferred; decision recorded when taken) | Production images, host config, health checks, deploy workflow |
| Scheduler | — | Run-once entry point so it works as a cron job; keep the loop for local Docker |
| Production Postgres (Neon, EU region) | Create project | Connection config; the existing migration workflow |
| Production auth (a *separate* Supabase project, never the dev one) | Create project; Google login for the domain; set redirect URLs | Config; use Resend as its email sender |
| File storage (R2 bucket) | Create bucket and keys | CORS rules for browser upload; config |
| Email (Resend) | Account; verify the domain (SPF/DKIM) | Config; sender address |
| AI provider (OpenRouter) | $10 credit (lifts the free limit to 1,000/day); later a paid model | Model selection and the quality test runner |
| Error tracking (Sentry) | Account | Integration that never sends customer data |
| Uptime monitoring (Uptime Kuma) | A small separate host (not the app host) | Health endpoints and check list |
| Address autocomplete (Geoapify) | Free key | Config |
| Stripe | Stays in **test mode** until legal/company are done | Webhook endpoint and live-mode switch checklist when ready |
| Staging vs production | — | Separate configuration for each; backup-restore test; short runbook |

---

# C. Pilot onboarding (how complimentary accounts work)

1. The tester signs up normally and creates their shop (and branches, if any).
2. Operator grants free access: `docker compose exec backend python -m app.cli.pilot_accounts grant --email tester@shop.ie` (in a hosted environment, the same command with that environment's database). It covers every shop they own, including branches.
3. They can add staff with **no payment step**; branches they add later are complimentary too. The Onboarding page shows "Complimentary (pilot)" instead of a Subscribe button.
4. `list` shows every complimentary account; `revoke --email ...` ends access.
5. **Converting to a paying customer needs no operator step:** the tester subscribes through the normal Stripe Checkout; the first real Stripe event replaces the placeholder and clears the flag. A real paying subscription is never overwritten by `grant`.

---

# D. Free-tier posture (measured/priced 05/10/2026 — re-check before relying on it)

| Service | Free allowance | Likely first paid trigger |
|---|---|---|
| OpenRouter | Free models: 50 requests/day (1,000/day after a $10 credit), unreliable | Switch to a paid model at pilot start (pennies) |
| Neon Postgres | 0.5 GB, 100 compute-hours/month | Compute first (the 15-minute scheduler keeps it awake); roughly $7-20/month paid |
| Supabase auth | 50,000 monthly users, but free projects pause after 7 days inactive | Pro ($25/month) at public launch |
| Cloudflare R2 | 10 GB (files are deleted after import) | Effectively never |
| Resend | 3,000 emails/month, 100/day | Hundreds of customers |
| Sentry | 5,000 errors/month, 1 user | First noisy bug or a second team member |
| Uptime Kuma | Self-hosted, free | A tiny separate host (a few euros) |
| Vercel / Render | Hobby tier not for commercial use; Render free sleeps | Paid plans from the first pilot if hosted there |
| Stripe | No fixed fee | 1.5% + €0.25 per card payment (~€1.45 on €80) |

Measured per-customer variable cost at paid rates: **about €1.6-2.0/month** (Stripe dominates). The cost model's AI assumption (€0.75-3.00) is roughly 25x too high.

---

# E. Open decisions

- Hosting direction (managed vs the documented Hetzner + Coolify).
- ORLA name clearance → domain (blocks the public site).
- Whether to add a branded sign-up flow vs invite-only "request access" for the pilot (recommended: request access).
- Legal/compliance outcomes from the founder's session (privacy notice, terms, data-processing terms, retention policy, VAT).

# Revision History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 06/10/2026 | Initial plan from the founder's decisions of 06/10/2026. |
