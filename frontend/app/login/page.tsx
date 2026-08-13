"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { requireSupabase } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { error: loginError } = await requireSupabase().auth.signInWithPassword({ email, password });
      if (loginError) {
        setError(loginError.message);
        return;
      }
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogleLogin() {
    setError(null);
    const { error: oauthError } = await requireSupabase().auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/onboarding`,
        // Forces Google's account-chooser screen instead of silently
        // re-authenticating through whatever Google session is already
        // live in the browser. The app has no way to end that Google
        // session itself (only Supabase's own session is ours to clear
        // on sign-out) — this makes the re-auth an explicit, visible
        // choice rather than something that looks like sign-out "didn't
        // work" when someone signs out and immediately clicks this again.
        queryParams: { prompt: "select_account" },
      },
    });
    if (oauthError) setError(oauthError.message);
  }

  return (
    <main className="auth-page">
      <div className="auth-card">
        <div className="auth-brand" aria-hidden="true"><span>OR</span> ORLA</div>
        <h1>Log in</h1>
        <p className="hint">Use your ORLA account to continue.</p>
        <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="email">Email</label>
          <br />
          <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <br />
          <input
            id="password"
            type={showPassword ? "text" : "password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div>
          <label>
            <input type="checkbox" checked={showPassword} onChange={(e) => setShowPassword(e.target.checked)} />
            {" "}Show password
          </label>
        </div>
        {error && <p className="status-error">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Logging in…" : "Log in"}
        </button>
        </form>
        <p>
          <a href="/forgot-password">Forgot password?</a>
        </p>
        <button className="auth-secondary-action" type="button" onClick={handleGoogleLogin}>
          Continue with Google
        </button>
        <p className="auth-footer">
          No account yet? <a href="/signup">Sign up</a>
        </p>
      </div>
    </main>
  );
}
