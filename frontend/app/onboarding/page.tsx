"use client";

import { useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api/client";
import { redirectToCheckout } from "@/lib/billing";
import { PROFILE_FIELDS_AFTER_ADDRESS, PROFILE_FIELDS_BEFORE_ADDRESS } from "@/lib/businessProfileFields";
import { useAddressAutocomplete } from "@/lib/hooks/useAddressAutocomplete";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type {
  AddressSuggestion,
  Business,
  EmployeeSeat,
  EmployeeSeatCreateResponse,
  Member,
  SubscriptionStatus,
} from "@/types";

// Only bicycle_shop exists today (roadmap Phase 2) — the dropdown already
// models this as a template choice, not a hardcoded assumption, so adding
// cafe/garage later is a new option here, not new UI.
const TEMPLATES = [{ value: "bicycle_shop", label: "Bicycle shop" }];

// The branch-creation flow's own form state — collects the full profile
// up front, all fields required, before a branch can proceed to payment
// (direct request). Shares its field names 1:1 with BusinessProfileUpdate
// (lib/businessProfileFields.ts) plus "name", which that type doesn't
// carry (the standalone/branch name isn't editable from the profile PATCH
// route — see [id]/page.tsx's own comment on that).
type BranchDraft = {
  name: string;
  manager_first_name: string;
  manager_surname: string;
  contact_email: string;
  contact_phone: string;
  location_label: string;
  address_line1: string;
  city: string;
  postal_code: string;
  country: string;
  timezone: string;
};

const EMPTY_BRANCH_DRAFT: BranchDraft = {
  name: "",
  manager_first_name: "",
  manager_surname: "",
  contact_email: "",
  contact_phone: "",
  location_label: "",
  address_line1: "",
  city: "",
  postal_code: "",
  country: "",
  timezone: "Europe/Dublin",
};

// Membership.ROLES minus "owner" — the account's existing owner is
// already the admin (product decision); a new paid seat is manager or
// staff, matching backend/app/application/employee_seats.py::
// EMPLOYEE_SEAT_ROLES exactly.
const EMPLOYEE_ROLES = [
  { value: "staff", label: "Staff" },
  { value: "manager", label: "Manager" },
];

type EmployeeDraft = {
  first_name: string;
  surname: string;
  email: string;
  role: string;
  address_line1: string;
  city: string;
  postal_code: string;
  country: string;
};
const EMPTY_EMPLOYEE_DRAFT: EmployeeDraft = {
  first_name: "",
  surname: "",
  email: "",
  role: "staff",
  address_line1: "",
  city: "",
  postal_code: "",
  country: "",
};

// Mirrors statusLabel below, but for an employee seat rather than a
// business's own subscription — deliberately not shown as "Subscribed"/
// "Cancelled" (those already mean something specific for a business) so
// the two concepts don't visually blur together in the same list.
// Real access needs BOTH payment (status "active") AND a linked account
// (account_linked) — whichever is still missing is what the label says,
// rather than a bare "Pending Payment" that would hide the other reason.
function seatStatusLabel(seat: { status: string; account_linked: boolean }): string {
  if (seat.status === "payment_failed") return "Payment failed";
  if (seat.status === "canceled") return "Removed";
  if (seat.status === "active" && seat.account_linked) return "Active";
  if (seat.status === "active") return "Paid — waiting for them to sign in";
  if (seat.account_linked) return "Pending payment";
  return "Pending payment and signup";
}

// The four states a business can actually be in, collapsed from the raw
// Stripe subscription status (active/past_due/incomplete/.../null) plus
// this app's own soft-delete flag — direct request: exactly these four
// labels, not the raw Stripe vocabulary.
function statusLabel(business: Business, subscriptionStatus: string | null): string {
  if (business.deleted_at) return "Deleted";
  if (subscriptionStatus === "active") return "Subscribed";
  if (subscriptionStatus === "canceled") return "Cancelled";
  return "Pending Payment";
}

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
  // Which business's inline "are you sure?" prompt is showing, if any —
  // replaces a prior window.confirm() (reported as doing nothing on at
  // least one real click; native confirm dialogs are also unreliable
  // inside some embedded/webview browser contexts, silently resolving
  // without ever showing anything) with a plain in-page Yes/No, the same
  // expand-in-place pattern already used for the branch form.
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  // Which standalone business's "Add a branch" form is expanded, if any —
  // only one open at a time, matching the create-business form's own
  // single-form-on-screen feel. Doubles as the businessId passed to
  // useAddressAutocomplete below: the parent's own id, since the branch
  // doesn't exist yet to scope the address-suggestions call against, and
  // that endpoint's business_id is only ever used for its membership gate
  // anyway (the caller being a member of the parent already proves that).
  const [branchFormOpenFor, setBranchFormOpenFor] = useState<string | null>(null);
  const [branchDraft, setBranchDraft] = useState<BranchDraft>(EMPTY_BRANCH_DRAFT);
  // Set once POST .../branches succeeds — lets a retry after a failed
  // profile save (network blip, etc.) only PATCH this same branch, never
  // create a second one. Mirrors this page's own existing
  // create-before-pay, resumable-if-abandoned pattern for Checkout itself.
  const [branchId, setBranchId] = useState<string | null>(null);
  const [branchSubmitting, setBranchSubmitting] = useState(false);
  const [branchError, setBranchError] = useState<string | null>(null);
  const branchAddress = useAddressAutocomplete(branchFormOpenFor);

  // Employee seats (EUR 5/month, up to 2 per business) — keyed by
  // business id; only ever fetched/shown for a business the caller owns
  // (the list route itself is owner-only, see app/api/employee_seats.py).
  const [employeeSeatsByBusiness, setEmployeeSeatsByBusiness] = useState<Record<string, EmployeeSeat[]>>({});
  // The owner + every employee, merged — GET .../members is visible to
  // any member (unlike the owner-only list above), so this is what
  // actually renders the "who's attached to this business" display;
  // employeeSeatsByBusiness above stays purely a lookup for the Edit
  // form (it has the email, which the display list deliberately omits).
  const [membersByBusiness, setMembersByBusiness] = useState<Record<string, Member[]>>({});
  // The business id the add/edit employee form is open for, if any — the
  // employee already exists as a real business here (unlike branchAddress
  // above), so address suggestions are scoped directly against it.
  const [employeeFormOpenFor, setEmployeeFormOpenFor] = useState<string | null>(null);
  // Set when the open form is editing an existing seat rather than
  // creating a new one — null means "add" (email is collected and a POST
  // is sent); set means "edit" (email stays fixed, a PATCH is sent).
  const [editingEmployeeSeatId, setEditingEmployeeSeatId] = useState<string | null>(null);
  const [employeeDraft, setEmployeeDraft] = useState<EmployeeDraft>(EMPTY_EMPLOYEE_DRAFT);
  const [employeeSubmitting, setEmployeeSubmitting] = useState(false);
  const [employeeError, setEmployeeError] = useState<string | null>(null);
  const employeeAddress = useAddressAutocomplete(employeeFormOpenFor);

  useEffect(() => {
    if (session) {
      // include_deleted=true — this list is now the "Company Profile"
      // view (linked from the top nav), which shows every business
      // including archived ones (status "Deleted") for visibility/
      // history. Every other page's business selector still calls plain
      // GET /businesses and never sees a deleted one.
      apiGet<Business[]>("/businesses?include_deleted=true").then(setBusinesses).catch(() => undefined);
    }
  }, [session]);

  useEffect(() => {
    businesses.forEach((b) => {
      if (b.deleted_at) return;
      apiGet<SubscriptionStatus>(`/businesses/${b.id}/billing/subscription`)
        .then((s) => setSubscriptions((prev) => ({ ...prev, [b.id]: s })))
        .catch(() => undefined);
    });
  }, [businesses]);

  useEffect(() => {
    businesses.forEach((b) => {
      // The list route itself is owner-only (app/api/employee_seats.py)
      // — skipping the call entirely for a non-owner membership avoids a
      // guaranteed, noisy 403 on every page load.
      if (b.deleted_at || b.role !== "owner") return;
      apiGet<EmployeeSeat[]>(`/businesses/${b.id}/employee-seats`)
        .then((seats) => setEmployeeSeatsByBusiness((prev) => ({ ...prev, [b.id]: seats })))
        .catch(() => undefined);
    });
  }, [businesses]);

  useEffect(() => {
    // Unlike the owner-only fetch above, GET .../members is visible to
    // any member — fetched for every non-deleted business regardless of
    // role, since this is what actually renders "who's attached here"
    // for a manager/staff viewer too, not just the owner.
    businesses.forEach((b) => {
      if (b.deleted_at) return;
      apiGet<Member[]>(`/businesses/${b.id}/members`)
        .then((members) => setMembersByBusiness((prev) => ({ ...prev, [b.id]: members })))
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

  function handleRequestDelete(businessId: string) {
    setDeleteError(null);
    setConfirmingDeleteId(businessId);
  }

  function handleCancelDelete() {
    setConfirmingDeleteId(null);
  }

  async function handleConfirmDelete(business: Business) {
    setDeleteError(null);
    setDeletingId(business.id);
    try {
      await apiDelete(`/businesses/${business.id}`);
      // Marked Deleted in place rather than removed from the list — this
      // page shows archived businesses now, not just active ones.
      setBusinesses((prev) =>
        prev.map((b) => (b.id === business.id ? { ...b, deleted_at: new Date().toISOString() } : b))
      );
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Could not delete the shop. Try again shortly.");
    } finally {
      setDeletingId(null);
      setConfirmingDeleteId(null);
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

  function handleOpenAddBranch(parentId: string) {
    setBranchFormOpenFor(parentId);
    setBranchDraft(EMPTY_BRANCH_DRAFT);
    setBranchId(null);
    setBranchError(null);
  }

  function handleCancelAddBranch() {
    const idToDelete = branchId;
    setBranchFormOpenFor(null);
    setBranchDraft(EMPTY_BRANCH_DRAFT);
    setBranchId(null);
    setBranchError(null);
    if (idToDelete) {
      // Best-effort cleanup, not awaited — a branch already created
      // mid-flow (profile unfinished, payment never reached) is
      // soft-deleted rather than left behind as an orphaned "Pending
      // Payment" row with a blank profile. Cancel closes the form
      // immediately either way; if this fails, the branch just sits there
      // exactly as any other abandoned "Pending Payment" branch already
      // does, still deletable normally from this same page.
      apiDelete(`/businesses/${idToDelete}`).catch(() => undefined);
    }
  }

  function updateBranchDraft(key: keyof BranchDraft, value: string) {
    setBranchDraft((prev) => ({ ...prev, [key]: value }));
  }

  function handleBranchAddressChange(value: string) {
    updateBranchDraft("address_line1", value);
    branchAddress.handleAddressChange(value);
  }

  function handleBranchPickSuggestion(suggestion: AddressSuggestion) {
    setBranchDraft((prev) => ({
      ...prev,
      address_line1: suggestion.address_line1 ?? prev.address_line1,
      city: suggestion.city ?? prev.city,
      postal_code: suggestion.postal_code ?? prev.postal_code,
      country: suggestion.country ?? prev.country,
      timezone: suggestion.timezone ?? prev.timezone,
    }));
    branchAddress.reset();
  }

  async function handleAddBranch(e: React.FormEvent, parentId: string) {
    e.preventDefault();
    setBranchError(null);
    setBranchSubmitting(true);
    try {
      // Create once, then only ever PATCH on a retry — branchId, set the
      // moment creation succeeds, is what makes that safe (see its own
      // comment above).
      let id = branchId;
      if (!id) {
        const branch = await apiPost<Business>(`/businesses/${parentId}/branches`, {
          name: branchDraft.name,
          template,
          timezone: branchDraft.timezone,
        });
        id = branch.id;
        setBranchId(id);
        // Shows up in the list right away as "Pending Payment" — same as
        // before, in case Checkout below is abandoned rather than
        // completed. The profile PATCH about to run fills in the rest.
        setBusinesses((prev) => [...prev, branch]);
      }
      await apiPatch<Business>(`/businesses/${id}`, {
        manager_first_name: branchDraft.manager_first_name,
        manager_surname: branchDraft.manager_surname,
        contact_email: branchDraft.contact_email,
        contact_phone: branchDraft.contact_phone,
        location_label: branchDraft.location_label,
        address_line1: branchDraft.address_line1,
        city: branchDraft.city,
        postal_code: branchDraft.postal_code,
        country: branchDraft.country,
        timezone: branchDraft.timezone,
      });
      // Straight into Stripe Checkout for the branch price — no
      // intermediate "sits here unpaid" step for the user to stall on.
      // If they abandon Checkout, the branch (now with a complete
      // profile) stays clearly marked "Pending Payment" with a resumable
      // "Complete payment" button below, rather than disappearing.
      await redirectToCheckout(id);
    } catch (err) {
      setBranchError(
        err instanceof ApiError ? err.message : "Could not save the branch profile. Is the backend running?"
      );
    } finally {
      setBranchSubmitting(false);
    }
  }

  function handleOpenAddEmployee(businessId: string) {
    setEmployeeFormOpenFor(businessId);
    setEditingEmployeeSeatId(null);
    setEmployeeDraft(EMPTY_EMPLOYEE_DRAFT);
    setEmployeeError(null);
  }

  function handleOpenEditEmployee(businessId: string, seat: EmployeeSeat) {
    setEmployeeFormOpenFor(businessId);
    setEditingEmployeeSeatId(seat.id);
    setEmployeeDraft({
      first_name: seat.first_name,
      surname: seat.surname,
      email: seat.email,
      role: seat.role,
      address_line1: seat.address_line1 ?? "",
      city: seat.city ?? "",
      postal_code: seat.postal_code ?? "",
      country: seat.country ?? "",
    });
    setEmployeeError(null);
  }

  function handleCancelEmployeeForm() {
    setEmployeeFormOpenFor(null);
    setEditingEmployeeSeatId(null);
    setEmployeeDraft(EMPTY_EMPLOYEE_DRAFT);
    setEmployeeError(null);
  }

  async function handleDeleteEmployee(businessId: string, seatId: string) {
    setEmployeeError(null);
    try {
      await apiDelete(`/businesses/${businessId}/employee-seats/${seatId}`);
      // Deletion always results in status "canceled" — updated in place
      // (not removed from either list) rather than re-fetched, matching
      // this app's soft-delete-and-show pattern elsewhere (a deleted
      // business still lists as "Deleted" rather than vanishing).
      setEmployeeSeatsByBusiness((prev) => ({
        ...prev,
        [businessId]: (prev[businessId] ?? []).map((s) => (s.id === seatId ? { ...s, status: "canceled" } : s)),
      }));
      setMembersByBusiness((prev) => ({
        ...prev,
        [businessId]: (prev[businessId] ?? []).map((m) =>
          m.employee_seat_id === seatId ? { ...m, status: "canceled" } : m
        ),
      }));
    } catch (err) {
      setEmployeeError(err instanceof ApiError ? err.message : "Could not remove this employee.");
    }
  }

  function updateEmployeeDraft(key: keyof EmployeeDraft, value: string) {
    setEmployeeDraft((prev) => ({ ...prev, [key]: value }));
  }

  function handleEmployeeAddressChange(value: string) {
    updateEmployeeDraft("address_line1", value);
    employeeAddress.handleAddressChange(value);
  }

  function handleEmployeeAddressPickSuggestion(suggestion: AddressSuggestion) {
    setEmployeeDraft((prev) => ({
      ...prev,
      address_line1: suggestion.address_line1 ?? prev.address_line1,
      city: suggestion.city ?? prev.city,
      postal_code: suggestion.postal_code ?? prev.postal_code,
      country: suggestion.country ?? prev.country,
    }));
    employeeAddress.reset();
  }

  async function handleSaveEmployee(e: React.FormEvent, businessId: string) {
    e.preventDefault();
    setEmployeeError(null);
    setEmployeeSubmitting(true);
    try {
      if (editingEmployeeSeatId) {
        const updated = await apiPatch<EmployeeSeat>(
          `/businesses/${businessId}/employee-seats/${editingEmployeeSeatId}`,
          {
            first_name: employeeDraft.first_name,
            surname: employeeDraft.surname,
            role: employeeDraft.role,
            address_line1: employeeDraft.address_line1 || null,
            city: employeeDraft.city || null,
            postal_code: employeeDraft.postal_code || null,
            country: employeeDraft.country || null,
          }
        );
        setEmployeeSeatsByBusiness((prev) => ({
          ...prev,
          [businessId]: (prev[businessId] ?? []).map((s) => (s.id === updated.id ? updated : s)),
        }));
        handleCancelEmployeeForm();
        return;
      }
      const { employee_seat, checkout_url } = await apiPost<EmployeeSeatCreateResponse>(
        `/businesses/${businessId}/employee-seats`,
        employeeDraft
      );
      // Shows up in the list right away as "Pending payment and signup",
      // same resumable-if-abandoned shape as a branch's own Checkout
      // handoff.
      setEmployeeSeatsByBusiness((prev) => ({
        ...prev,
        [businessId]: [...(prev[businessId] ?? []), employee_seat],
      }));
      window.location.href = checkout_url;
    } catch (err) {
      // The backend's own message is specific per failure (already
      // invited, seat limit reached, ...) — shown directly rather than a
      // generic fallback.
      setEmployeeError(
        err instanceof ApiError ? err.message : "Could not save this employee. Is the backend running?"
      );
    } finally {
      setEmployeeSubmitting(false);
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
  // doesn't count, and neither does an already-deleted one (the real
  // limit check on the backend excludes both the same way; this list
  // now shows deleted businesses too, so this must filter them out
  // itself or a deleted shop would wrongly keep the create form hidden).
  const hasStandaloneShop = businesses.some((b) => !b.parent_business_id && !b.deleted_at);

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
            if (b.deleted_at) {
              // Archived — shown for visibility/history only. No actions:
              // nothing here is editable or resumable once deleted (the
              // backend itself 404s a PATCH/DELETE against it).
              const parent = b.parent_business_id
                ? businesses.find((p) => p.id === b.parent_business_id)
                : null;
              return (
                <li key={b.id} style={{ marginBottom: "1em" }}>
                  <div className="hint">
                    {parent ? <>↳ Branch of {parent.name} — </> : null}
                    {b.name} — {b.template} ({b.role})
                  </div>
                  <div className="hint">Deleted</div>
                </li>
              );
            }

            const status = subscriptions[b.id]?.status ?? null;
            const label = statusLabel(b, status);
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
            const canUpload = label === "Subscribed";
            return (
              <li key={b.id} style={{ marginBottom: "1em" }}>
                <div>
                  <strong>
                    {parent ? <span className="hint">↳ Branch of {parent.name} — </span> : null}
                    {b.name}
                  </strong>{" "}
                  — {b.template} ({b.role}) —{" "}
                  <span className={label === "Subscribed" ? "status-ok" : "status-error"}>{label}</span>
                </div>
                <div>
                  {canUpload ? (
                    <a href={`/uploads?business=${b.id}`}>Upload data</a>
                  ) : (
                    <span className="hint">Upload data (subscribe first)</span>
                  )}
                  {" — "}
                  <a href={`/onboarding/${b.id}`}>View profile</a>
                </div>
                <div>
                  {isRecoverableInPortal ? (
                    <button type="button" disabled={busy} onClick={() => handleManageBilling(b.id)}>
                      {busy ? "Opening…" : "Manage billing"}
                    </button>
                  ) : (
                    <button type="button" disabled={busy} onClick={() => handleSubscribe(b.id)}>
                      {busy
                        ? "Starting…"
                        : b.parent_business_id
                          ? "Complete payment (€30/mo)"
                          : "Subscribe"}
                    </button>
                  )}
                </div>
                {/* Its own line, ahead of the more incidental actions below
                    (delete) — "we are missing the button to add more
                    branches" was reported directly after it was buried at
                    the end of one long run-on line of buttons; only shown
                    for a standalone shop, since a branch can't itself have
                    branches. */}
                {isStandalone && (
                  <div>
                    <button
                      type="button"
                      onClick={() =>
                        branchFormOpenFor === b.id ? handleCancelAddBranch() : handleOpenAddBranch(b.id)
                      }
                    >
                      {branchFormOpenFor === b.id ? "Cancel" : "+ Add a branch (€30/mo)"}
                    </button>
                  </div>
                )}
                {isStandalone && branchFormOpenFor === b.id && (
                  <form onSubmit={(e) => handleAddBranch(e, b.id)}>
                    <h3>Branch profile</h3>
                    <p className="hint">
                      Every field below is required before this branch can proceed to payment — it&apos;s
                      what tells this location apart from {b.name} once you have more than one.
                    </p>
                    <div>
                      <label htmlFor={`branch-name-${b.id}`}>Branch name</label>
                      <br />
                      <input
                        id={`branch-name-${b.id}`}
                        required
                        value={branchDraft.name}
                        onChange={(e) => updateBranchDraft("name", e.target.value)}
                      />
                    </div>
                    {PROFILE_FIELDS_BEFORE_ADDRESS.map(({ key, label: fieldLabel, type }) => (
                      <div key={key}>
                        <label htmlFor={`branch-${key}-${b.id}`}>{fieldLabel}</label>
                        <br />
                        <input
                          id={`branch-${key}-${b.id}`}
                          type={type ?? "text"}
                          required
                          value={branchDraft[key]}
                          onChange={(e) => updateBranchDraft(key, e.target.value)}
                        />
                      </div>
                    ))}
                    {/* Same live-suggestion address input as the profile edit
                        page (useAddressAutocomplete), scoped against this
                        branch's own not-yet-created id via the parent's —
                        see branchAddress's own declaration above for why
                        that's safe. */}
                    <div style={{ position: "relative" }}>
                      <label htmlFor={`branch-address-${b.id}`}>Address</label>
                      <br />
                      <input
                        id={`branch-address-${b.id}`}
                        autoComplete="off"
                        required
                        value={branchDraft.address_line1}
                        onChange={(e) => handleBranchAddressChange(e.target.value)}
                        onFocus={branchAddress.openIfHasSuggestions}
                        onBlur={branchAddress.closeSoon}
                      />
                      {branchAddress.suggestLoading && <span className="hint"> Searching…</span>}
                      {branchAddress.suggestOpen && branchAddress.suggestions.length > 0 && (
                        <ul
                          style={{
                            position: "absolute",
                            zIndex: 1,
                            margin: 0,
                            padding: 0,
                            listStyle: "none",
                            background: "Canvas",
                            color: "CanvasText",
                            border: "1px solid #ccc",
                            width: "100%",
                            maxWidth: "32em",
                          }}
                        >
                          {branchAddress.suggestions.map((suggestion, i) => (
                            <li key={i}>
                              <button
                                type="button"
                                onClick={() => handleBranchPickSuggestion(suggestion)}
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
                        <label htmlFor={`branch-${key}-${b.id}`}>{fieldLabel}</label>
                        <br />
                        <input
                          id={`branch-${key}-${b.id}`}
                          required
                          value={branchDraft[key]}
                          onChange={(e) => updateBranchDraft(key, e.target.value)}
                        />
                      </div>
                    ))}
                    {branchError && <p className="status-error">{branchError}</p>}
                    <button type="submit" disabled={branchSubmitting}>
                      {branchSubmitting ? "Saving…" : "Save and continue to payment"}
                    </button>{" "}
                    <button type="button" disabled={branchSubmitting} onClick={handleCancelAddBranch}>
                      Cancel
                    </button>
                  </form>
                )}
                {/* Employee seats — owner/admin-only, on any business the
                    caller owns (standalone or branch, unlike "Add a
                    branch" which is standalone-only: a branch is its own
                    fully separate, separately-billed entity). */}
                {b.role === "owner" && (
                  <div>
                    <button
                      type="button"
                      onClick={() =>
                        employeeFormOpenFor === b.id ? handleCancelEmployeeForm() : handleOpenAddEmployee(b.id)
                      }
                    >
                      {employeeFormOpenFor === b.id ? "Cancel" : "+ Add employee (€5/mo)"}
                    </button>
                  </div>
                )}
                {b.role === "owner" && employeeFormOpenFor === b.id && (
                  <form onSubmit={(e) => handleSaveEmployee(e, b.id)}>
                    <h3>{editingEmployeeSeatId ? "Edit employee" : "Employee profile"}</h3>
                    {!editingEmployeeSeatId && (
                      <p className="hint">
                        They don&apos;t need an account yet — if this email hasn&apos;t signed up at{" "}
                        <a href="/signup">/signup</a>, access activates automatically the first time they
                        do, as long as payment has also gone through. Both need to happen before they can
                        get in.
                      </p>
                    )}
                    <div>
                      <label htmlFor={`employee-first-name-${b.id}`}>First name</label>
                      <br />
                      <input
                        id={`employee-first-name-${b.id}`}
                        required
                        value={employeeDraft.first_name}
                        onChange={(e) => updateEmployeeDraft("first_name", e.target.value)}
                      />
                    </div>
                    <div>
                      <label htmlFor={`employee-surname-${b.id}`}>Surname</label>
                      <br />
                      <input
                        id={`employee-surname-${b.id}`}
                        required
                        value={employeeDraft.surname}
                        onChange={(e) => updateEmployeeDraft("surname", e.target.value)}
                      />
                    </div>
                    <div>
                      <label htmlFor={`employee-email-${b.id}`}>Email</label>
                      <br />
                      <input
                        id={`employee-email-${b.id}`}
                        type="email"
                        required
                        disabled={!!editingEmployeeSeatId}
                        value={employeeDraft.email}
                        onChange={(e) => updateEmployeeDraft("email", e.target.value)}
                      />
                      {editingEmployeeSeatId && (
                        <span className="hint">
                          {" "}
                          Not editable here — changing it would break matching them to their account.
                        </span>
                      )}
                    </div>
                    <div>
                      <label htmlFor={`employee-role-${b.id}`}>Role</label>
                      <br />
                      <select
                        id={`employee-role-${b.id}`}
                        value={employeeDraft.role}
                        onChange={(e) => updateEmployeeDraft("role", e.target.value)}
                      >
                        {EMPLOYEE_ROLES.map((r) => (
                          <option key={r.value} value={r.value}>
                            {r.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    {/* Same live-suggestion address input as the owner's
                        own profile and the branch-creation form — scoped
                        directly against this real business's own id. */}
                    <div style={{ position: "relative" }}>
                      <label htmlFor={`employee-address-${b.id}`}>Address (optional)</label>
                      <br />
                      <input
                        id={`employee-address-${b.id}`}
                        autoComplete="off"
                        value={employeeDraft.address_line1}
                        onChange={(e) => handleEmployeeAddressChange(e.target.value)}
                        onFocus={employeeAddress.openIfHasSuggestions}
                        onBlur={employeeAddress.closeSoon}
                      />
                      {employeeAddress.suggestLoading && <span className="hint"> Searching…</span>}
                      {employeeAddress.suggestOpen && employeeAddress.suggestions.length > 0 && (
                        <ul
                          style={{
                            position: "absolute",
                            zIndex: 1,
                            margin: 0,
                            padding: 0,
                            listStyle: "none",
                            background: "Canvas",
                            color: "CanvasText",
                            border: "1px solid #ccc",
                            width: "100%",
                            maxWidth: "32em",
                          }}
                        >
                          {employeeAddress.suggestions.map((suggestion, i) => (
                            <li key={i}>
                              <button
                                type="button"
                                onClick={() => handleEmployeeAddressPickSuggestion(suggestion)}
                                style={{ display: "block", width: "100%", textAlign: "left" }}
                              >
                                {suggestion.formatted_address}
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div>
                      <label htmlFor={`employee-city-${b.id}`}>City</label>
                      <br />
                      <input
                        id={`employee-city-${b.id}`}
                        value={employeeDraft.city}
                        onChange={(e) => updateEmployeeDraft("city", e.target.value)}
                      />
                    </div>
                    <div>
                      <label htmlFor={`employee-postal-code-${b.id}`}>Postal code</label>
                      <br />
                      <input
                        id={`employee-postal-code-${b.id}`}
                        value={employeeDraft.postal_code}
                        onChange={(e) => updateEmployeeDraft("postal_code", e.target.value)}
                      />
                    </div>
                    <div>
                      <label htmlFor={`employee-country-${b.id}`}>Country</label>
                      <br />
                      <input
                        id={`employee-country-${b.id}`}
                        value={employeeDraft.country}
                        onChange={(e) => updateEmployeeDraft("country", e.target.value)}
                      />
                    </div>
                    {employeeError && <p className="status-error">{employeeError}</p>}
                    <button type="submit" disabled={employeeSubmitting}>
                      {employeeSubmitting
                        ? "Saving…"
                        : editingEmployeeSeatId
                          ? "Save changes"
                          : "Save and continue to payment"}
                    </button>{" "}
                    <button type="button" disabled={employeeSubmitting} onClick={handleCancelEmployeeForm}>
                      Cancel
                    </button>
                  </form>
                )}
                {/* The owner + every employee, in one list — visible to
                    any member (GET .../members), not owner-only, per
                    direct request: "Mauricio Ruiz - Owner" / "Antonio
                    Ruiz - Manager". Edit/Delete only render for the
                    caller's own owner view, and only on employee rows —
                    there's no "delete the owner" action here (that's
                    "Delete this shop" below, which already cancels
                    billing and archives the whole business). */}
                {(membersByBusiness[b.id]?.length ?? 0) > 0 && (
                  <div>
                    <h3>Team</h3>
                    <ul>
                      {membersByBusiness[b.id].map((member) => {
                        const displayName =
                          member.first_name || member.surname
                            ? `${member.first_name} ${member.surname}`.trim()
                            : member.role === "owner"
                              ? "(add your name in Company Profile)"
                              : "(unnamed)";
                        const roleLabel = member.role.charAt(0).toUpperCase() + member.role.slice(1);
                        const seatId = member.employee_seat_id;
                        const fullSeat = seatId
                          ? employeeSeatsByBusiness[b.id]?.find((s) => s.id === seatId)
                          : undefined;
                        return (
                          <li key={member.employee_seat_id ?? member.user_id ?? member.role} className="hint">
                            {displayName} - {roleLabel}
                            {seatId && (
                              <>
                                {" — "}
                                <span
                                  className={
                                    member.status === "active" && member.account_linked
                                      ? "status-ok"
                                      : "status-error"
                                  }
                                >
                                  {seatStatusLabel(member)}
                                </span>
                              </>
                            )}
                            {b.role === "owner" && seatId && fullSeat && (
                              <>
                                {" "}
                                <button type="button" onClick={() => handleOpenEditEmployee(b.id, fullSeat)}>
                                  Edit
                                </button>{" "}
                                {member.status !== "canceled" && (
                                  <button type="button" onClick={() => handleDeleteEmployee(b.id, seatId)}>
                                    Delete
                                  </button>
                                )}
                              </>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
                <div>
                  {confirmingDeleteId === b.id ? (
                    <span>
                      Delete &quot;{b.name}&quot;? This cancels its subscription and archives the shop —
                      your sales, products, and reports stay on record, but you&apos;ll lose access to
                      them here.{" "}
                      <button type="button" disabled={deleting} onClick={() => handleConfirmDelete(b)}>
                        {deleting ? "Deleting…" : "Yes, delete"}
                      </button>{" "}
                      <button type="button" disabled={deleting} onClick={handleCancelDelete}>
                        No
                      </button>
                    </span>
                  ) : (
                    <button type="button" onClick={() => handleRequestDelete(b.id)}>
                      Delete this shop
                    </button>
                  )}
                </div>
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
