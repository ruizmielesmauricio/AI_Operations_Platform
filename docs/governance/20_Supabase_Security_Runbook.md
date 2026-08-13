# 20_Supabase_Security_Runbook.md

**Version:** 1.0
**Status:** Active
**Author:** Founder & CTO (dashboard steps) / Claude (drafted)
**Last Updated:** 13/08/2026
**Related:** `docs/decisions/ADR-024-supabase-session-security.md`, `backend/app/security/auth.py`, `docs/governance/11_Development_Roadmap.md`

---

## Purpose

ORLA delegates 100% of authentication to Supabase Auth (`docs/decisions/ADR-013`). Two categories of work close the remaining security/account gaps around password resets and email/password changes, and neither is something application code can do on its own:

1. **A handful of Supabase project-dashboard settings** — no API access exists for these from this codebase, and no MCP tool available to this session exposes an "update auth config" call either (confirmed by inspecting the connected Supabase MCP server's tool list before writing this document — only read-only/project-management tools like `get_advisors`, `list_tables`, `execute_sql` exist, nothing for auth configuration).
2. **One manual, empirical two-browser-session test** — proving a password reset actually invalidates another device's session needs two real signed-in sessions on one real account. That needs an existing account's real password entered into two real login forms, which falls under this environment's own standing rule against an agent entering authentication credentials, and no disposable account exists to test with either (creating one is equally out of bounds — see `docs/governance/11_Development_Roadmap.md` v1.62–v1.66 for the same constraint disclosed every time a two-role walkthrough came up).

Both need a human with real access. This document is that person's checklist.

---

## Part A — Supabase dashboard configuration

All steps are in the [Supabase dashboard](https://supabase.com/dashboard) for ORLA's project, under **Authentication**.

### A1. Enable security notification emails

1. Go to **Authentication → Emails** (email templates live here; security notifications are configured alongside them, project-level).
2. Enable, at minimum:
   - **Password Changed**
   - **Email Address Changed**
3. Leave the rest (Phone Changed, Sign-in method linked/removed, etc.) off unless a feature that needs them ships later — ORLA has no phone auth or MFA today, so those categories can never fire and enabling them now would just be dead configuration.
4. These emails go to the affected account only — never to staff, never surfaced as an in-app ORLA notification (per the original prompt's explicit "no security event should be sent to staff or become a noisy general notification").

### A2. Confirm Secure Email Change stays enabled

1. **Authentication → Providers → Email** (or **Authentication → Settings**, depending on current dashboard layout).
2. Confirm **Secure email change** is **on** — this makes an email-address change require confirmation from both the old and new address, not just the new one. It should already be Supabase's default; this step is a confirmation, not a change.
3. Do **not** replace Supabase's reset/confirmation emails with a custom Send Email Hook — that would make ORLA responsible for secure email delivery and token handling it doesn't need to own (see `ADR-024`'s reasoning for why this codebase avoids taking on auth responsibility Supabase already carries correctly).

### A3. Confirm redirect URL allowlist

1. **Authentication → URL Configuration**.
2. Confirm the **Redirect URLs** allowlist includes:
   - ORLA's deployed production URL (`.../reset-password`, `.../onboarding` — whatever the live domain resolves to)
   - The local development URL (`http://localhost:3000/reset-password` and equivalents), if local dev sign-in is still in active use
3. Any URL *not* on this list will have its reset/confirmation links silently fail to redirect correctly — worth a quick manual click-through after confirming, not just a visual check of the list.

### A4. Confirm Auth Audit Log retention and note the reviewer

1. **Authentication → Configuration → Audit Logs** (or the dashboard's current equivalent path — this is a newer Supabase feature, the exact location may have moved since this was written).
2. Confirm audit logs are being written (default: yes, to both `auth.audit_log_entries` in Postgres and external log storage — a toggle exists to disable the Postgres copy specifically to save DB storage, without losing the external copy).
3. Record here once confirmed:
   - **Retention window on the current plan:** _(fill in — depends on Supabase project plan; Free/Pro plans have shorter windows than Team/Enterprise)_
   - **Export option available:** _(fill in — dashboard-only viewing vs. a queryable Logs Explorer vs. a log drain, depending on plan)_
   - **Person/role responsible for periodic review:** _(fill in — the founder, until a dedicated security role exists)_
4. What gets logged (from Supabase's own documentation, useful for anyone reviewing this later): `user_recovery_requested` (reset requested), `user_updated_password` (password change completed), `token_revoked` (a refresh token — including the ones this round's `signOut({scope:"others"})` call revokes — invalidated), `token_refreshed`, `user_signedup`, `login`, `logout`, among others. This is the authoritative record for every one of these events — ORLA's own `AuditLog` table is deliberately **not** a duplicate of this (see `backend/app/security/auth.py`'s own docstring: "ORLA does not fabricate a local audit event it cannot prove the provider committed").

---

## Part B — Manual two-session password-reset verification

**Who can run this:** anyone with a real ORLA test account and two separate browsers or devices. Not something this session can execute — see Purpose above.

**Goal:** prove that after a password reset, a session that was signed in *before* the reset can no longer refresh its token or call an authenticated ORLA API, while the session that performed the reset can.

### Steps

1. Note the `@supabase/supabase-js` version in use at the time of the test (currently `^2.45.0`, `frontend/package.json`) — record it below, since SDK behavior for `signOut({scope:"others"})` is what's under test.
2. Sign in to ORLA on **Browser/Device A**. Confirm you land on `/dashboard` or `/onboarding` successfully.
3. Sign in to the **same account** on **Browser/Device B** (a different browser, or a private/incognito window counts as a separate session — a second tab in the same browser does **not**, since it shares the same session storage).
4. On Device A, confirm you can still load an authenticated page (e.g. refresh `/dashboard`).
5. Go to `/forgot-password`, request a reset for this account's email.
6. Open the reset email, click the link — this should open `/reset-password` with a valid recovery session (confirm the page does *not* show "Link invalid or expired").
7. **Complete the reset on Device A** (choose a new password, submit). Wait for the redirect to `/onboarding`.
8. **On Device B**, without signing in again, try to load or refresh an authenticated page (e.g. `/dashboard`), or wait for its next background poll (e.g. the notifications unread-count refresh, `AppNav.tsx`, which polls every 60s) and check the browser's network tab for a 401.
   - **Expected:** Device B's request fails (401, or Supabase's client-side `getSession()`/`onAuthStateChange` reports no valid session) — the refresh token `signOut({scope:"others"})` revoked should no longer work.
9. **On Device A**, confirm the app still works normally post-reset (navigate to another page, confirm no re-login is required) — Device A's session should be untouched, since `scope: "others"` deliberately excludes the current session.
10. Sign out of both devices when done (test hygiene — do not leave a test account's sessions open indefinitely).

### Record the outcome here

- **Date run:** _(fill in)_
- **`@supabase/supabase-js` version:** _(fill in)_
- **Device A result:** _(fill in — expected: stayed signed in, fully functional)_
- **Device B result:** _(fill in — expected: session invalidated, 401 on next authenticated call)_
- **Pass/Fail:** _(fill in)_
- **If Fail:** do not add a service-role key or Admin API fallback without re-reading `ADR-024`'s reasoning first — a failure here most likely means the `signOut({scope:"others"})` call itself isn't reaching Supabase correctly (check the browser console for the `console.error` logged in `frontend/app/reset-password/page.tsx` on a `revokeError`), not that the underlying mechanism doesn't exist.

---

## Part C — Manual email-change verification (optional, same category of test)

Same "needs a real signed-in session" constraint as Part B. If run:

1. From a signed-in session, trigger an email change (wherever ORLA exposes this — currently via Supabase's own `updateUser({ email })` if/when a settings UI calls it; confirm this exists before testing, since no dedicated frontend UI for it was found as of this writing).
2. Confirm the secure-email-change flow requires confirming from **both** the old and new address (per A2 above).
3. Confirm a "Email address changed" notification email arrives once confirmed (per A1).
4. Confirm the event appears in Supabase's Auth Audit Logs (per A4).
5. Confirm nothing about the change — no token, no OTP, no email content — appears in ORLA's own backend logs or `AuditLog` table.
