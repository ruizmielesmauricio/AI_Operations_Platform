"use client";

import { useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api/client";
import { redirectToCheckout } from "@/lib/billing";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { Business, SubscriptionStatus } from "@/types";

// Only bicycle_shop exists today (roadmap Phase 2) — the dropdown already
// models this as a template choice, not a hardcoded assumption, so adding
// cafe/garage later is a new option here, not new UI.
const TEMPLATES = [{ value: "bicycle_shop", label: "Bicycle shop" }];

export default function OnboardingPage() {
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
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Which standalone business's "Add a branch" form is expanded, if any —
  // only one open at a time, matching the create-business form's own
  // single-form-on-screen feel.
  const [branchFormOpenFor, setBranchFormOpenFor] = useState<string | null>(null);
  const [branchName, setBranchName] = useState("");
  const [branchTimezone, setBranchTimezone] = useState("Europe/Dublin");
  const [branchSubmitting, setBranchSubmitting] = useState(false);
  const [branchError, setBranchError] = useState<string | null>(null);

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

  async function handleSubscribe(businessId: string) {
    setBillingError(null);
    setBillingBusyId(businessId);
    try {
      await redirectToCheckout(businessId);
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

  async function handleDelete(business: Business) {
    // Deletion cancels real billing and is not something to fire on a
    // stray click — a native confirm rather than a new modal component
    // for one button, matching this frontend's existing lack of one.
    const confirmed = window.confirm(
      `Delete "${business.name}"? This cancels its subscription and archives the shop — your sales, ` +
        "products, and reports stay on record, but you'll lose access to them here."
    );
    if (!confirmed) return;

    setDeleteError(null);
    setDeletingId(business.id);
    try {
      await apiDelete(`/businesses/${business.id}`);
      setBusinesses((prev) => prev.filter((b) => b.id !== business.id));
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Could not delete the shop. Try again shortly.");
    } finally {
      setDeletingId(null);
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
    } catch (err) {
      // A 409 (one shop per account) carries its own honest, user-facing
      // message from the backend — shown directly rather than the
      // generic fallback. The create form is normally hidden once a
      // standalone business already exists (see below), so reaching this
      // branch at all would mean a stale page/race, not the common path.
      setError(err instanceof ApiError ? err.message : "Could not create the business. Is the backend running?");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAddBranch(e: React.FormEvent, parentId: string) {
    e.preventDefault();
    setBranchError(null);
    setBranchSubmitting(true);
    try {
      const branch = await apiPost<Business>(`/businesses/${parentId}/branches`, {
        name: branchName,
        template,
        timezone: branchTimezone,
      });
      // Straight into Stripe Checkout for the branch price — no
      // intermediate "sits here unpaid" step for the user to stall on.
      // If they abandon Checkout, the branch row still exists (the same
      // create-before-pay shape every standalone shop already uses) and
      // stays clearly marked "payment incomplete" with a resumable
      // "Complete payment" button below, rather than disappearing.
      await redirectToCheckout(branch.id);
    } catch (err) {
      setBranchError(err instanceof ApiError ? err.message : "Could not add the branch. Is the backend running?");
    } finally {
      setBranchSubmitting(false);
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

  // One standalone shop per account — a branch (parent_business_id set)
  // doesn't count, so someone whose only business is a branch (shouldn't
  // normally happen, but not impossible after a parent's deleted) still
  // sees the create form rather than being wrongly locked out of it.
  const hasStandaloneShop = businesses.some((b) => !b.parent_business_id);

  return (
    <main>
      <AppNav />
      <h1>Your businesses</h1>
      {billingError && <p className="status-error">{billingError}</p>}
      {deleteError && <p className="status-error">{deleteError}</p>}
      {businesses.length === 0 ? (
        <p>No business yet — create your first one below.</p>
      ) : (
        <ul>
          {businesses.map((b) => {
            const status = subscriptions[b.id]?.status ?? null;
            // A recoverable subscription (past_due, incomplete…) sends the
            // owner to the Customer Portal to fix it — new payment method,
            // retry, etc. A canceled subscription is a dead end there (no
            // "resubscribe" option in the Portal once a subscription has
            // actually ended), so it's treated the same as no subscription:
            // a fresh Checkout. Starting a new Checkout on top of a
            // recoverable one would just create a second, unrelated
            // subscription, which is why only "canceled"/null fall through.
            const isRecoverableInPortal = status !== null && status !== "canceled";
            const busy = billingBusyId === b.id;
            const deleting = deletingId === b.id;
            const parent = b.parent_business_id
              ? businesses.find((p) => p.id === b.parent_business_id)
              : null;
            const isStandalone = !b.parent_business_id;
            // The upload/import routes are already hard-gated server-side
            // (require_active_subscription, 402 without an active
            // subscription) — this link used to render unconditionally
            // regardless of status, which looked like real access from
            // here even though the actual upload would be rejected.
            // Matching the link's visibility to the real gate closes that
            // false impression rather than just leaving it to a 402 the
            // user only discovers after clicking through.
            const canUpload = status === "active";
            return (
              <li key={b.id}>
                {parent ? <span className="hint">↳ Branch of {parent.name} — </span> : null}
                {b.name} — {b.template} ({b.role})
                {" — "}
                {canUpload ? (
                  <a href={`/uploads?business=${b.id}`}>Upload data</a>
                ) : (
                  <span className="hint">Upload data (subscribe first)</span>
                )}
                {" — "}
                {isRecoverableInPortal ? (
                  <>
                    <span className={status === "active" ? "status-ok" : "status-error"}>
                      {status === "active" ? "subscribed" : `subscription ${status}`}
                    </span>{" "}
                    <button type="button" disabled={busy} onClick={() => handleManageBilling(b.id)}>
                      {busy ? "Opening…" : "Manage billing"}
                    </button>
                  </>
                ) : (
                  <>
                    <span>
                      {status === "canceled"
                        ? "subscription canceled"
                        : b.parent_business_id
                          ? "payment incomplete"
                          : "not subscribed"}
                    </span>{" "}
                    <button type="button" disabled={busy} onClick={() => handleSubscribe(b.id)}>
                      {busy
                        ? "Starting…"
                        : b.parent_business_id
                          ? "Complete payment (€30/mo)"
                          : "Subscribe"}
                    </button>
                  </>
                )}
                {" — "}
                <button type="button" disabled={deleting} onClick={() => handleDelete(b)}>
                  {deleting ? "Deleting…" : "Delete this shop"}
                </button>
                {isStandalone && (
                  <>
                    {" — "}
                    <button
                      type="button"
                      onClick={() =>
                        setBranchFormOpenFor(branchFormOpenFor === b.id ? null : b.id)
                      }
                    >
                      {branchFormOpenFor === b.id ? "Cancel" : "Add a branch (€30/mo)"}
                    </button>
                  </>
                )}
                {isStandalone && branchFormOpenFor === b.id && (
                  <form onSubmit={(e) => handleAddBranch(e, b.id)}>
                    <div>
                      <label htmlFor={`branch-name-${b.id}`}>Branch name</label>
                      <br />
                      <input
                        id={`branch-name-${b.id}`}
                        required
                        value={branchName}
                        onChange={(e) => setBranchName(e.target.value)}
                      />
                    </div>
                    <div>
                      <label htmlFor={`branch-timezone-${b.id}`}>Timezone</label>
                      <br />
                      <input
                        id={`branch-timezone-${b.id}`}
                        value={branchTimezone}
                        onChange={(e) => setBranchTimezone(e.target.value)}
                      />
                    </div>
                    {branchError && <p className="status-error">{branchError}</p>}
                    <button type="submit" disabled={branchSubmitting}>
                      {branchSubmitting ? "Adding…" : "Add branch"}
                    </button>
                  </form>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {hasStandaloneShop ? (
        <p className="hint">
          One standalone shop per account — delete your existing shop above to create a different one, or
          use "Add a branch" on it to add another location for €30/month.
        </p>
      ) : (
        <>
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
        </>
      )}
    </main>
  );
}
