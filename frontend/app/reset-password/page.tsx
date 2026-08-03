"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { requireSupabase, supabase } from "@/lib/supabase/client";

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
      const { error: updateError } = await requireSupabase().auth.updateUser({ password });
      if (updateError) {
        setError(updateError.message);
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
