"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { requireSupabase } from "@/lib/supabase/client";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");

  // Prefills from an employee invite link (?email=...) — window.location
  // directly, not next/navigation's useSearchParams, matching this
  // codebase's existing pattern (frontend/lib/hooks/useBusinessSelector.ts)
  // for reading a query param without needing a Suspense boundary just
  // for a static page. Still fully editable — the email address they
  // sign up with is what actually matters, this only saves retyping it.
  useEffect(() => {
    const invited = new URLSearchParams(window.location.search).get("email");
    if (invited) setEmail(invited);
  }, []);

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmationPending, setConfirmationPending] = useState(false);
  const [resent, setResent] = useState(false);

  function describeError(message: string): string {
    if (message.toLowerCase().includes("already registered")) {
      return "An account with that email already exists. Log in instead, or use \"Continue with Google\" if that's how you originally signed up.";
    }
    return message;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }
    setSubmitting(true);
    try {
      const { data, error: signupError } = await requireSupabase().auth.signUp({ email, password });
      if (signupError) {
        setError(describeError(signupError.message));
        return;
      }
      if (!data.session) {
        // Email confirmation is required — Supabase didn't hand back a
        // session yet, so there's nothing to onboard into until it's clicked.
        setConfirmationPending(true);
        return;
      }
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setError(null);
    setResent(false);
    const { error: resendError } = await requireSupabase().auth.resend({ type: "signup", email });
    if (resendError) {
      setError(resendError.message);
      return;
    }
    setResent(true);
  }

  async function handleGoogleSignup() {
    setError(null);
    const { error: oauthError } = await requireSupabase().auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/onboarding`,
        // See the matching comment in app/login/page.tsx — forces an
        // explicit account choice rather than a silent re-auth off an
        // existing Google browser session.
        queryParams: { prompt: "select_account" },
      },
    });
    if (oauthError) setError(oauthError.message);
  }

  if (confirmationPending) {
    return (
      <main>
        <h1>Check your email</h1>
        <p>We sent a confirmation link to {email}. Click it to finish creating your account.</p>
        {resent && <p className="status-ok">Confirmation email resent.</p>}
        {error && <p className="status-error">{error}</p>}
        <button type="button" onClick={handleResend}>
          Resend confirmation email
        </button>
      </main>
    );
  }

  return (
    <main>
      <h1>Create your account</h1>
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
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="confirmPassword">Retype password</label>
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
          {submitting ? "Creating account…" : "Sign up"}
        </button>
      </form>
      <button type="button" onClick={handleGoogleSignup}>
        Continue with Google
      </button>
      <p>
        Already have an account? <a href="/login">Log in</a>
      </p>
    </main>
  );
}
