"use client";

import { useState } from "react";
import { requireSupabase } from "@/lib/supabase/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { error: resetError } = await requireSupabase().auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (resetError) {
        setError(resetError.message);
        return;
      }
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <main>
        <h1>Check your email</h1>
        <p>If an account exists for {email}, we&apos;ve sent a link to reset the password.</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Reset your password</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="email">Email</label>
          <br />
          <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        {error && <p className="status-error">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Sending…" : "Send reset link"}
        </button>
      </form>
      <p>
        <a href="/login">Back to log in</a>
      </p>
    </main>
  );
}
