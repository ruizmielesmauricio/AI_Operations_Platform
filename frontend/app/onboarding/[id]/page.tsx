"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppNav } from "@/components/AppNav";
import { ApiError, apiGet, apiPatch } from "@/lib/api/client";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { Business, BusinessProfileUpdate, SubscriptionStatus } from "@/types";

// Descriptive contact/location record-keeping only — not a second login
// (confirmed with the user, see backend/app/models/business.py). Most
// useful once an account has more than one location and the shop `name`
// alone doesn't distinguish them. name/template are deliberately not
// editable here — renaming a business has wider display implications
// this page doesn't take on.
const PROFILE_FIELDS: { key: keyof BusinessProfileUpdate; label: string }[] = [
  { key: "manager_name", label: "Manager / owner name" },
  { key: "contact_email", label: "Contact email" },
  { key: "contact_phone", label: "Contact phone" },
  { key: "location_label", label: "Location label (e.g. \"Dublin - Rathmines\")" },
  { key: "address_line1", label: "Address" },
  { key: "city", label: "City" },
  { key: "postal_code", label: "Postal code" },
  { key: "country", label: "Country" },
  { key: "timezone", label: "Timezone" },
];

function formFromBusiness(business: Business): BusinessProfileUpdate {
  return {
    manager_name: business.manager_name ?? "",
    contact_email: business.contact_email ?? "",
    contact_phone: business.contact_phone ?? "",
    location_label: business.location_label ?? "",
    address_line1: business.address_line1 ?? "",
    city: business.city ?? "",
    postal_code: business.postal_code ?? "",
    country: business.country ?? "",
    timezone: business.timezone ?? "",
  };
}

// Same collapse as frontend/app/onboarding/page.tsx's statusLabel — kept
// as a separate small copy rather than a shared import, since the two
// pages' surrounding logic (deleted-row short-circuiting, subscribe
// buttons) differs enough that sharing just this one function isn't worth
// a new lib file yet.
function statusLabel(business: Business, subscriptionStatus: string | null): string {
  if (business.deleted_at) return "Deleted";
  if (subscriptionStatus === "active") return "Subscribed";
  if (subscriptionStatus === "canceled") return "Cancelled";
  return "Pending Payment";
}

export default function BusinessProfilePage() {
  const { session, checkingSession } = useRequireSession();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const businessId = params.id;

  const [business, setBusiness] = useState<Business | null>(null);
  const [subscriptionStatus, setSubscriptionStatus] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<BusinessProfileUpdate>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!session || !businessId) return;
    apiGet<Business>(`/businesses/${businessId}`)
      .then((b) => {
        setBusiness(b);
        setForm(formFromBusiness(b));
      })
      .catch((err) => {
        // A deleted business 404s here (same as a nonexistent one) — the
        // backend never allows editing an archived business's profile,
        // and there's no read-only view built for one either, so this is
        // an honest dead end rather than a broken form.
        setLoadError(
          err instanceof ApiError && err.status === 404
            ? "This shop wasn't found — it may have been deleted."
            : "Could not load this shop. Is the backend running?"
        );
      });
  }, [session, businessId]);

  useEffect(() => {
    if (!businessId) return;
    apiGet<SubscriptionStatus>(`/businesses/${businessId}/billing/subscription`)
      .then((s) => setSubscriptionStatus(s.status))
      .catch(() => undefined);
  }, [businessId]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaveError(null);
    setSaving(true);
    try {
      // Blank strings mean "clear this field" as much as "never set it" —
      // sent through as-is (empty string, not omitted) so an owner can
      // deliberately clear a field they'd previously filled in.
      await apiPatch<Business>(`/businesses/${businessId}`, form);
      router.push("/onboarding");
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Could not save. Is the backend running?");
      setSaving(false);
    }
  }

  function handleCancel() {
    router.push("/onboarding");
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

  if (loadError) {
    return (
      <main>
        <AppNav />
        <p className="status-error">{loadError}</p>
        <a href="/onboarding">← Back to Company Profile</a>
      </main>
    );
  }

  if (!business) {
    return (
      <main>
        <AppNav />
        <p>Loading…</p>
      </main>
    );
  }

  const label = statusLabel(business, subscriptionStatus);

  return (
    <main>
      <AppNav businessId={business.id} />
      <p>
        <a href="/onboarding">← Back to Company Profile</a>
      </p>
      <h1>{business.name}</h1>
      <p>
        {business.template} ({business.role}) —{" "}
        <span className={label === "Subscribed" ? "status-ok" : "status-error"}>{label}</span>
        {business.parent_business_id && " — Branch"}
      </p>

      <form onSubmit={handleSave}>
        {PROFILE_FIELDS.map(({ key, label: fieldLabel }) => (
          <div key={key}>
            <label htmlFor={`profile-${key}`}>{fieldLabel}</label>
            <br />
            <input
              id={`profile-${key}`}
              value={form[key] ?? ""}
              onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
            />
          </div>
        ))}
        {saveError && <p className="status-error">{saveError}</p>}
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>{" "}
        <button type="button" disabled={saving} onClick={handleCancel}>
          Cancel
        </button>
      </form>
    </main>
  );
}
