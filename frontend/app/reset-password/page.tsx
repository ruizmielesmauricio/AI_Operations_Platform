"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { requireSupabase, supabase } from "@/lib/supabase/client";
import { apiPost } from "@/lib/api/client";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [checkingLink, setCheckingLink] = useState(true);
  const [linkValid, setLinkValid] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!supabase) {
      setCheckingLink(false);
      return;
    }
    // The recovery link's tokens are in the URL; the client resolves them
    // into a session as part of its startup, which getSession() awaits.
    supabase.auth.getSession().then(({ data }) => {
      setLinkValid(!!data.session);
      setCheckingLink(false);
    });
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }
    setSubmitting(true);
    try {
      const client = requireSupabase();
      const { error: updateError } = await client.auth.updateUser({ password });
      if (updateError) {
        setError(updateError.message);
        return;
      }
      // Immediately revoke ORLA API access for old access JWTs. The
      // provider's refresh-token revocation below remains necessary, but
      // its effect otherwise waits for another browser's access token to
      // expire. This endpoint trusts only this verified recovery session.
      await apiPost<{ revoked: boolean }>("/account/security/revoke-other-sessions", {});
      // Explicitly revoke every other session's refresh token now that the
      // password has changed — this account may still be signed in on
      // another device, and that device should not stay usable past this
      // point. `scope: "others"` is Supabase's own documented, provider-
      // native mechanism for exactly this (see ADR-024): it uses the
      // recovery session established by the reset link itself, so it needs
      // no new secret and it deliberately leaves *this* session (the one
      // that just set the new password) alone.
      const { error: revokeError } = await client.auth.signOut({ scope: "others" });
      if (revokeError) {
        setError("Your password was changed, but we could not sign out your other sessions. Request a new reset link and try again.");
        return;
      }
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  if (checkingLink) {
    return (
      <main>
        <p>Checking link…</p>
      </main>
    );
  }

  if (!linkValid) {
    return (
      <main>
        <h1>Link invalid or expired</h1>
        <p>
          <a href="/forgot-password">Request a new password reset link</a>.
        </p>
      </main>
    );
  }

  return (
    <main>
      <h1>Choose a new password</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="password">New password</label>
          <br />
          <input
            id="password"
            type={showPassword ? "text" : "password"}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="confirmPassword">Retype new password</label>
          <br />
          <input
            id="confirmPassword"
            type={showPassword ? "text" : "password"}
            required
            minLength={8}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
        </div>
        <div>
          <label>
            <input type="checkbox" checked={showPassword} onChange={(e) => setShowPassword(e.target.checked)} />
            {" "}Show passwords
          </label>
        </div>
        {error && <p className="status-error">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Saving…" : "Save new password"}
        </button>
      </form>
    </main>
  );
}
