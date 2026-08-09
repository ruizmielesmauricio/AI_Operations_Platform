"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppNav } from "@/components/AppNav";
import { ApiError, apiGet, apiPatch } from "@/lib/api/client";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { AddressSuggestion, Business, BusinessProfileUpdate, SubscriptionStatus } from "@/types";

// Descriptive contact/location record-keeping only — not a second login
// (confirmed with the user, see backend/app/models/business.py). Most
// useful once an account has more than one location and the shop `name`
// alone doesn't distinguish them. name/template are deliberately not
// editable here — renaming a business has wider display implications
// this page doesn't take on.
//
// address_line1 is deliberately not in this generic list — it gets its
// own live-suggestion input below (direct request: suggestions as you
// type, like any modern address field, not a separate click-to-validate
// step). city/postal_code/country/timezone stay in this list too, still
// directly editable, since picking a suggestion only fills them in as a
// starting point — an owner can still correct any of them by hand
// afterward, same as before.
// Split around the custom Address input below so the field order on
// screen stays exactly what it was before (manager/contact/location,
// then address, then city/postal/country/timezone) without a map() that
// has to special-case one key in the middle of the list.
const PROFILE_FIELDS_BEFORE_ADDRESS: { key: keyof BusinessProfileUpdate; label: string }[] = [
  { key: "manager_name", label: "Manager / owner name" },
  { key: "contact_email", label: "Contact email" },
  { key: "contact_phone", label: "Contact phone" },
  { key: "location_label", label: "Location label (e.g. \"Dublin - Rathmines\")" },
];
const PROFILE_FIELDS_AFTER_ADDRESS: { key: keyof BusinessProfileUpdate; label: string }[] = [
  { key: "city", label: "City" },
  { key: "postal_code", label: "Postal code" },
  { key: "country", label: "Country" },
  { key: "timezone", label: "Timezone" },
];

// Debounced after typing stops, and only once there's enough text to
// plausibly match something — keeps request volume reasonable against
// Geoapify's free-tier cap without needing a manual trigger.
const ADDRESS_SUGGEST_DEBOUNCE_MS = 350;
const ADDRESS_SUGGEST_MIN_CHARS = 3;

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
  // Live address suggestions — a dropdown under the Address input, not a
  // separate click-to-validate step. suggestOpen tracks whether the
  // dropdown should render at all (closed on blur-via-selection, on a
  // too-short query, and once a suggestion is applied) independent of
  // whether `suggestions` still holds stale results from a moment ago.
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

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

    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (value.trim().length < ADDRESS_SUGGEST_MIN_CHARS) {
      setSuggestions([]);
      setSuggestOpen(false);
      return;
    }
    debounceRef.current = setTimeout(() => {
      setSuggestLoading(true);
      apiGet<AddressSuggestion[]>(`/businesses/${businessId}/address-suggestions?text=${encodeURIComponent(value)}`)
        .then((results) => {
          setSuggestions(results);
          setSuggestOpen(results.length > 0);
        })
        .catch(() => {
          // Quiet failure, matching backend/app/geocoding/service.py's own
          // posture — a live-suggestion field just showing no dropdown is
          // normal UX while typing, not something to interrupt with an
          // error banner.
          setSuggestions([]);
          setSuggestOpen(false);
        })
        .finally(() => setSuggestLoading(false));
    }, ADDRESS_SUGGEST_DEBOUNCE_MS);
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
    setSuggestOpen(false);
    setSuggestions([]);
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
        {PROFILE_FIELDS_BEFORE_ADDRESS.map(({ key, label: fieldLabel }) => (
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
            onFocus={() => {
              if (suggestions.length > 0) setSuggestOpen(true);
            }}
            onBlur={() => {
              // A short delay, not an immediate close — a direct blur-then-
              // click on a suggestion would otherwise close the dropdown
              // before the click's own handler ever fires.
              setTimeout(() => setSuggestOpen(false), 150);
            }}
          />
          {suggestLoading && <span className="hint"> Searching…</span>}
          {suggestOpen && suggestions.length > 0 && (
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
              {suggestions.map((suggestion, i) => (
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
    </main>
  );
}
