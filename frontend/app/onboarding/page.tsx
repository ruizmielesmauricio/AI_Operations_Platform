"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPost } from "@/lib/api/client";
import { supabase } from "@/lib/supabase/client";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { Business, SubscriptionStatus } from "@/types";

// Only bicycle_shop exists today (roadmap Phase 2) — the dropdown already
// models this as a template choice, not a hardcoded assumption, so adding
// cafe/garage later is a new option here, not new UI.
const TEMPLATES = [{ value: "bicycle_shop", label: "Bicycle shop" }];

export default function OnboardingPage() {
  const router = useRouter();
  const { session, checkingSession } = useRequireSession();
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [subscriptions, setSubscriptions] = useState<Record<string, SubscriptionStatus>>({});
  const [name, setName] = useState("");
  const [template, setTemplate] = useState(TEMPLATES[0].value);
  const [timezone, setTimezone] = useState("Europe/Dublin");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [billingBusyId, setBillingBusyId] = useState<string | null>(null);
  const [billingError, setBillingError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      apiGet<Business[]>("/businesses").then(setBusinesses).catch(() => undefined);
    }
  }, [session]);

  useEffect(() => {
    businesses.forEach((b) => {
      apiGet<SubscriptionStatus>(`/businesses/${b.id}/billing/subscription`)
        .then((s) => setSubscriptions((prev) => ({ ...prev, [b.id]: s })))
        .catch(() => undefined);
    });
  }, [businesses]);

  async function handleLogout() {
    await supabase?.auth.signOut();
    router.push("/login");
  }

  async function handleSubscribe(businessId: string) {
    setBillingError(null);
    setBillingBusyId(businessId);
    try {
      const { checkout_url } = await apiPost<{ checkout_url: string }>(
        `/businesses/${businessId}/billing/checkout-session`,
        {}
      );
      window.location.href = checkout_url;
    } catch {
      setBillingError("Could not start checkout. Is the backend running?");
      setBillingBusyId(null);
    }
  }

  async function handleManageBilling(businessId: string) {
    setBillingError(null);
    setBillingBusyId(businessId);
    try {
      const { portal_url } = await apiPost<{ portal_url: string }>(
        `/businesses/${businessId}/billing/portal-session`,
        {}
      );
      window.location.href = portal_url;
    } catch {
      setBillingError("Could not open the billing portal. Is the backend running?");
      setBillingBusyId(null);
    }
  }

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

  if (!session) {
    return (
      <main>
        <p>Supabase is not configured yet — set NEXT_PUBLIC_SUPABASE_URL/ANON_KEY in frontend/.env.local.</p>
      </main>
    );
  }

  return (
    <main>
      <button type="button" onClick={handleLogout}>
        Log out
      </button>
      <h1>Your businesses</h1>
      {billingError && <p className="status-error">{billingError}</p>}
      {businesses.length === 0 ? (
        <p>No business yet — create your first one below.</p>
      ) : (
        <ul>
          {businesses.map((b) => {
            const isActive = subscriptions[b.id]?.status === "active";
            const busy = billingBusyId === b.id;
            return (
              <li key={b.id}>
                {b.name} — {b.template} ({b.role})
                {" — "}
                {isActive ? (
                  <>
                    <span className="status-ok">subscribed</span>{" "}
                    <button type="button" disabled={busy} onClick={() => handleManageBilling(b.id)}>
                      {busy ? "Opening…" : "Manage billing"}
                    </button>
                  </>
                ) : (
                  <>
                    <span>
                      {subscriptions[b.id]?.status
                        ? `subscription ${subscriptions[b.id]?.status}`
                        : "not subscribed"}
                    </span>{" "}
                    <button type="button" disabled={busy} onClick={() => handleSubscribe(b.id)}>
                      {busy ? "Starting…" : "Subscribe"}
                    </button>
                  </>
                )}
              </li>
            );
          })}
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
