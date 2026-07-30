"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPost } from "@/lib/api/client";
import { supabase } from "@/lib/supabase/client";
import type { Business } from "@/types";

// Only bicycle_shop exists today (roadmap Phase 2) — the dropdown already
// models this as a template choice, not a hardcoded assumption, so adding
// cafe/garage later is a new option here, not new UI.
const TEMPLATES = [{ value: "bicycle_shop", label: "Bicycle shop" }];

export default function OnboardingPage() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState(true);
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [name, setName] = useState("");
  const [template, setTemplate] = useState(TEMPLATES[0].value);
  const [timezone, setTimezone] = useState("Europe/Dublin");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!supabase) {
      setError("Supabase is not configured yet — set NEXT_PUBLIC_SUPABASE_URL/ANON_KEY in frontend/.env.local.");
      setCheckingSession(false);
      return;
    }
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.push("/login");
        return;
      }
      setCheckingSession(false);
      apiGet<Business[]>("/businesses").then(setBusinesses).catch(() => undefined);
    });
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const business = await apiPost<Business>("/businesses", { name, template, timezone });
      setBusinesses((prev) => [...prev, business]);
      setName("");
    } catch {
      setError("Could not create the business. Is the backend running?");
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

  return (
    <main>
      <h1>Your businesses</h1>
      {businesses.length === 0 ? (
        <p>No business yet — create your first one below.</p>
      ) : (
        <ul>
          {businesses.map((b) => (
            <li key={b.id}>
              {b.name} — {b.template} ({b.role})
            </li>
          ))}
        </ul>
      )}

      <h2>Create a business</h2>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="name">Business name</label>
          <br />
          <input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="template">Business type</label>
          <br />
          <select id="template" value={template} onChange={(e) => setTemplate(e.target.value)}>
            {TEMPLATES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="timezone">Timezone</label>
          <br />
          <input id="timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
        </div>
        {error && <p className="status-error">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Creating…" : "Create business"}
        </button>
      </form>
    </main>
  );
}
