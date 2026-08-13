# ADR-024: Close the password-reset session-revocation gap with Supabase's native `signOut({scope: "others"})`, not a service-role fallback

**Status:** Accepted
**Date:** 2026-08-13
**Related:** `backend/app/security/auth.py`, `frontend/app/reset-password/page.tsx`, `docs/governance/20_Supabase_Security_Runbook.md`, `docs/governance/11_Development_Roadmap.md`

## Decision

After a successful password reset, ORLA now explicitly revokes every *other* active session for that account using Supabase Auth's own documented client-SDK method, called from the browser at the exact moment the reset completes:

```ts
await client.auth.updateUser({ password });   // already existed
await client.auth.signOut({ scope: "others" }); // new
```

`frontend/app/reset-password/page.tsx` is the only file changed. **No `SUPABASE_SERVICE_ROLE_KEY` was added, no Supabase Admin API client was built, and no new backend route was created.**

This directly closes the gap `backend/app/security/auth.py` had disclosed since the Notifications/Security/Retention round: "revoking other sessions... needs a service-role key that doesn't exist."

## Reason

The prior assumption — recorded honestly at the time — was that session revocation could only happen through Supabase's Admin API, which requires a service-role key never provisioned in this deployment. Investigating that assumption before building anything (per this round's own explicit instruction not to add a service-role key without first checking) surfaced a simpler mechanism: `signOut()` accepts a `scope` parameter, and Supabase's own reference documents `scope: "others"` as "sign out of all other sessions, keep the current one" — callable by any authenticated user against their *own* account, using the session already on hand. The recovery session created by clicking the reset-password email link *is* such a session, so the reset-password page can call this immediately after the password itself is saved, with no elevated credential of any kind.

This is strictly better than the service-role fallback the original gap description anticipated:
- **No new secret to provision, store, or ever leak.** The single biggest risk `backend/app/security/auth.py` flagged about a hypothetical Admin API client — "must be impossible to import from browser code," "fail closed for privileged admin calls" — doesn't apply, because there is no privileged call.
- **No new backend surface.** No route, no idempotency/retry design, no JWT-resolution-not-browser-supplied-ID concern — none of that machinery is needed when the operation is a same-account, user-scoped SDK call.
- **Matches this project's existing delegation model exactly.** `auth.py`'s own docstring: "ORLA owns NOTHING about authentication itself." A backend-owned revocation endpoint would have been a small step toward owning session management in parallel with Supabase; this keeps that boundary intact.

## What this does *not* resolve on its own

The acceptance criterion in the originating prompt is empirical, not just architectural: *"confirm B cannot refresh its session or call an authenticated ORLA API after the change."* Proving that requires two real, signed-in browser sessions on one real account, which needs an existing account's real password entered into a real login form — something this environment's own standing rule prohibits an agent from doing (entering authentication credentials), and no account exists to test with disposably (creating one is equally prohibited). This is the same category of gap this session has disclosed every time a genuine two-role/two-session walkthrough came up (see `docs/governance/11_Development_Roadmap.md` v1.62–v1.66).

**Resolution:** the exact two-session test script is written out step by step in `docs/governance/20_Supabase_Security_Runbook.md` for a human with real credentials to run and record the result. Until that's done, treat this as "correctly implemented per Supabase's documented API contract" rather than "empirically proven end-to-end" — the same distinction this codebase already draws everywhere else it depends on Supabase's documented behavior without re-testing Supabase's own server internals (e.g. JWKS verification, refresh-token rotation).

## Alternatives Considered

**Build the service-role Admin API fallback anyway, as originally scoped.** Rejected — it would add a real secret and a real privileged code path to solve a problem Supabase's public client SDK already solves without one. Building the riskier option first, only to find the safer one afterward, would leave a service-role key in the deployment for no remaining reason.

**Do nothing until the live two-session test can be run.** Rejected — the fix itself is correct and safe to ship regardless of when the empirical proof happens (calling `signOut({scope:"others"})` cannot make a legitimate session *less* secure, it can only fail to revoke one it should have, which is the same failure mode the "gap" already had). Shipping it now and recording the outstanding verification honestly is more useful than blocking a safe fix on a test only a human can run.

**Revoke sessions from the backend instead, using the already-verified JWT of the *new* session right after login.** Considered and rejected as unnecessary complexity — it would require a new authenticated backend route, plus reasoning about *which* session is "current" from the backend's stateless-JWT vantage point, to do exactly what one client-side SDK call already does with less code and no backend involvement at all.

## Consequences

- `backend/app/security/auth.py`'s own disclosure comment updated to reflect this as closed, not blocked.
- No change to `backend/app/settings/config.py`, `backend/.env.example`, or any backend route — this is a pure frontend change.
- The `SUPABASE_SERVICE_ROLE_KEY` gap is retired from the roadmap's open-items list entirely, not deferred.
- `docs/governance/20_Supabase_Security_Runbook.md` carries the one piece of work still outstanding: a human running the live two-session test and the Supabase dashboard configuration steps (security notification emails, redirect URL allowlist) neither this ADR nor any code change can perform.

## Future Review Criteria

Revisit only if Supabase ever deprecates or changes `signOut({scope: "others"})`'s semantics (watch the supabase-js changelog on `@supabase/supabase-js` version bumps), or if a future requirement needs revocation triggered from somewhere *other* than the user's own already-authenticated browser (e.g. an owner force-revoking a compromised employee's session remotely) — that use case genuinely would need the Admin API and a service-role key, and should get its own ADR rather than retrofitting this one.
