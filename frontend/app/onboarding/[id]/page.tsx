"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppNav } from "@/components/AppNav";
import { ApiError, apiGet, apiPatch } from "@/lib/api/client";
import { PROFILE_FIELDS_AFTER_ADDRESS, PROFILE_FIELDS_BEFORE_ADDRESS } from "@/lib/businessProfileFields";
import { useAddressAutocomplete } from "@/lib/hooks/useAddressAutocomplete";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { AddressSuggestion, Business, BusinessProfileUpdate, SubscriptionStatus } from "@/types";

// Descriptive contact/location record-keeping only — not a second login
// (confirmed with the user, see backend/app/models/business.py). Most
// useful once an account has more than one location and the shop `name`
// alone doesn't distinguish them. name/template are deliberately not
// editable here — renaming a business has wider display implications
// this page doesn't take on.
//
// address_line1 is deliberately not in the shared field list
// (lib/businessProfileFields.ts) — it gets its own live-suggestion input
// below (direct request: suggestions as you type, like any modern address
// field, not a separate click-to-validate step). city/postal_code/
// country/timezone stay in that list too, still directly editable, since
// picking a suggestion only fills them in as a starting point — an owner
// can still correct any of them by hand afterward, same as before.

function formFromBusiness(business: Business): BusinessProfileUpdate {
  return {
    manager_first_name: business.manager_first_name ?? "",
    manager_surname: business.manager_surname ?? "",
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
  // Live address suggestions — a dropdown under the Address input, not a
  // separate click-to-validate step.
  const address = useAddressAutocomplete(businessId ?? null);

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

  function handleAddressChange(value: string) {
    setForm((prev) => ({ ...prev, address_line1: value }));
    address.handleAddressChange(value);
  }

  function handlePickSuggestion(suggestion: AddressSuggestion) {
    setForm((prev) => ({
      ...prev,
      address_line1: suggestion.address_line1 ?? prev.address_line1,
      city: suggestion.city ?? prev.city,
      postal_code: suggestion.postal_code ?? prev.postal_code,
      country: suggestion.country ?? prev.country,
      // Still just a starting point, not forced — an owner who knows
      // better can still overwrite any of these fields by hand afterward.
      timezone: suggestion.timezone ?? prev.timezone,
    }));
    address.reset();
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
  const canEdit = business.role === "owner";

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

      {!canEdit && (
        // Read-only for staff/manager (Company Profile permissions
        // batch) — the backend already 403s a non-owner PATCH here, but
        // showing an editable form with a Save button that predictably
        // fails is exactly the dead-end UI the product rule calls out.
        // Same field list/order as the editable form below, read
        // straight off `business` rather than the edit-only `form` state.
        <dl>
          {PROFILE_FIELDS_BEFORE_ADDRESS.map(({ key, label: fieldLabel }) => (
            <div key={key}>
              <dt>{fieldLabel}</dt>
              <dd>{business[key] || "—"}</dd>
            </div>
          ))}
          <div>
            <dt>Address</dt>
            <dd>{business.address_line1 || "—"}</dd>
          </div>
          {PROFILE_FIELDS_AFTER_ADDRESS.map(({ key, label: fieldLabel }) => (
            <div key={key}>
              <dt>{fieldLabel}</dt>
              <dd>{business[key] || "—"}</dd>
            </div>
          ))}
          <p className="hint">Only the shop&apos;s owner can edit the company profile.</p>
        </dl>
      )}

      {canEdit && (
      <form onSubmit={handleSave}>
        {PROFILE_FIELDS_BEFORE_ADDRESS.map(({ key, label: fieldLabel, type }) => (
          <div key={key}>
            <label htmlFor={`profile-${key}`}>{fieldLabel}</label>
            <br />
            <input
              id={`profile-${key}`}
              type={type ?? "text"}
              value={form[key] ?? ""}
              onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
            />
          </div>
        ))}

        {/* Live suggestions as you type, direct request — not a separate
            click-to-validate step. Picking one fills address_line1/city/
            postal_code/country/timezone below directly; every field stays
            editable by hand afterward regardless. */}
        <div style={{ position: "relative" }}>
          <label htmlFor="profile-address_line1">Address</label>
          <br />
          <input
            id="profile-address_line1"
            autoComplete="off"
            value={form.address_line1 ?? ""}
            onChange={(e) => handleAddressChange(e.target.value)}
            onFocus={address.openIfHasSuggestions}
            onBlur={address.closeSoon}
          />
          {address.suggestLoading && <span className="hint"> Searching…</span>}
          {address.suggestOpen && address.suggestions.length > 0 && (
            <ul
              style={{
                position: "absolute",
                zIndex: 1,
                margin: 0,
                padding: 0,
                listStyle: "none",
                // CSS system colors, not a hardcoded white — this app relies
                // on `color-scheme: light dark` (frontend/app/globals.css)
                // for automatic native dark-mode adaptation everywhere else,
                // no CSS variables of its own defined to hook into instead.
                background: "Canvas",
                color: "CanvasText",
                border: "1px solid #ccc",
                width: "100%",
                maxWidth: "32em",
              }}
            >
              {address.suggestions.map((suggestion, i) => (
                <li key={i}>
                  <button
                    type="button"
                    onClick={() => handlePickSuggestion(suggestion)}
                    style={{ display: "block", width: "100%", textAlign: "left" }}
                  >
                    {suggestion.formatted_address}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {PROFILE_FIELDS_AFTER_ADDRESS.map(({ key, label: fieldLabel }) => (
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
      )}
    </main>
  );
}
