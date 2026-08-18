"use client";

import { useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { requireSupabase, supabase } from "@/lib/supabase/client";
import { useRequireSession } from "@/lib/supabase/useRequireSession";

// Account-level settings tied to the Supabase Auth identity itself, not
// any one business — change-login-email specifically. Direct request,
// found missing during a gap review: the only `updateUser(...)` call
// anywhere in this frontend was reset-password's own `{ password }`
// call — there was no page/form anywhere that could ever call
// `updateUser({ email })`. No backend route needed for this: Supabase
// owns the entire email-change flow (sends its own confirmation email,
// updates the identity once confirmed), and
// backend/app/security/auth.py already re-syncs the local `User.email`
// mirror from the JWT on every request the moment the change actually
// takes effect — this page only ever needs to make the one client SDK
// call.
export default function AccountPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, loaded: businessesLoaded } = useBusinessSelector(session);
  // Direct request: change-login-email is owner-only. `Business.role` is
  // already the caller's own role on that business (GET /businesses is
  // tenant-scoped to the caller's own memberships), so no extra fetch is
  // needed — "owner" on at least one business is enough to treat this as
  // an owner account, since this app's model has never shown one person
  // holding a staff/manager role somewhere while also owning nothing.
  // IMPORTANT CAVEAT, disclosed rather than silently assumed away: this
  // is a frontend-only gate. `supabase.auth.updateUser({ email })` is a
  // direct client SDK call with no backend route of ours in the path (see
  // this file's own top comment) — there is nothing server-side of ours
  // to check a role against. A staff member could still technically call
  // it themselves via the browser console; closing that would mean
  // routing this through a backend endpoint using Supabase's Admin API
  // instead, which needs a SUPABASE_SERVICE_ROLE_KEY this project has
  // deliberately avoided everywhere else (see ADR-024). Flagging this
  // rather than overstating what's actually enforced.
  const isOwner = businesses.some((b) => b.role === "owner");

  const [currentEmail, setCurrentEmail] = useState<string | null>(null);
  // Whether this account actually has a password credential at all —
  // Google-only accounts (frontend/app/login/page.tsx's own OAuth path)
  // have none, and asking them to reauthenticate with a password they've
  // never set would be a dead end, not real security. Read from
  // Supabase's own `identities` array rather than assumed.
  const [hasPasswordIdentity, setHasPasswordIdentity] = useState<boolean | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmationSent, setConfirmationSent] = useState(false);

  useEffect(() => {
    if (!session || !supabase) return;
    supabase.auth.getUser().then(({ data }) => {
      setCurrentEmail(data.user?.email ?? null);
      setHasPasswordIdentity((data.user?.identities ?? []).some((identity) => identity.provider === "email"));
    });
  }, [session]);

  // Direct request: reauthenticate with the current password before a
  // sensitive account change like this proceeds — the session cookie
  // alone (which could be a while-you-were-away browser tab, or a
  // shared/borrowed device) shouldn't be enough on its own to redirect
  // where the account's own login mail goes. Supabase has no separate
  // "verify this password without disturbing the session" call — the
  // standard, documented pattern is the same `signInWithPassword` the
  // login page itself already uses, which simply fails (without
  // otherwise changing anything) if the password is wrong.
  async function reauthenticate(): Promise<boolean> {
    if (!currentEmail) {
      setError("Could not confirm your account email — try reloading the page.");
      return false;
    }
    if (!currentPassword) {
      setError("Enter your current password to confirm this change");
      return false;
    }
    const { error: authError } = await requireSupabase().auth.signInWithPassword({
      email: currentEmail,
      password: currentPassword,
    });
    if (authError) {
      setError("Current password is incorrect");
      return false;
    }
    return true;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setConfirmationSent(false);
    if (newEmail !== confirmEmail) {
      setError("Email addresses don't match");
      return;
    }
    if (newEmail === currentEmail) {
      setError("That's already your current login email");
      return;
    }
    setSubmitting(true);
    try {
      if (hasPasswordIdentity && !(await reauthenticate())) {
        return;
      }
      const { error: updateError } = await requireSupabase().auth.updateUser({ email: newEmail });
      if (updateError) {
        setError(updateError.message);
        return;
      }
      setConfirmationSent(true);
      setCurrentPassword("");
      setNewEmail("");
      setConfirmEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  if (checkingSession) {
    return (
      <main>
        <p>Checking session…</p>
      </main>
    );
  }

  if (!session) {
    return (
      <main>
        <p>Supabase is not configured yet — set NEXT_PUBLIC_SUPABASE_URL/ANON_KEY in frontend/.env.local.</p>
      </main>
    );
  }

  return (
    <main>
      <AppNav businessId={businessId} />
      <h1>Account</h1>
      <p className="hint">Your login email — used to sign in, not tied to any one business.</p>

      <p>
        <strong>Current login email:</strong> {currentEmail ?? "…"}
      </p>

      {confirmationSent && (
        <p className="status-ok">
          Check your new email inbox for a confirmation link. Your login email won&apos;t change until you click
          it — depending on this account&apos;s security settings, you may need to confirm from your old address
          too before the change takes effect.
        </p>
      )}

      <h2>Change login email</h2>
      {!businessesLoaded ? (
        <p>Loading…</p>
      ) : isOwner ? (
        <form onSubmit={handleSubmit}>
          <div>
            <label htmlFor="newEmail">New email</label>
            <br />
            <input
              id="newEmail"
              type="email"
              required
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="confirmEmail">Retype new email</label>
            <br />
            <input
              id="confirmEmail"
              type="email"
              required
              value={confirmEmail}
              onChange={(e) => setConfirmEmail(e.target.value)}
            />
          </div>
          {hasPasswordIdentity && (
            <div>
              <label htmlFor="currentPassword">Current password (to confirm this change)</label>
              <br />
              <input
                id="currentPassword"
                type="password"
                required
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
            </div>
          )}
          {hasPasswordIdentity === false && (
            <p className="hint">
              This account signs in with Google, not a password — no reauthentication step is needed here.
            </p>
          )}
          {error && <p className="status-error">{error}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Sending confirmation…" : "Change email"}
          </button>
        </form>
      ) : (
        <p className="hint">Only shop owners can change their login email. Contact your shop owner if this needs to change.</p>
      )}

      <p>
        Need to change your password instead? <a href="/forgot-password">Reset your password</a>.
      </p>
    </main>
  );
}
