"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { GlobalSearchBar } from "@/components/GlobalSearchBar";
import { API_URL, apiGet } from "@/lib/api/client";
import { businessDisplayLabel } from "@/lib/businessLabel";
import { useCurrentMember } from "@/lib/hooks/useCurrentMember";
import { onNotificationsChanged } from "@/lib/notificationsBus";
import { supabase } from "@/lib/supabase/client";
import type { Business, SubscriptionStatus, SystemStatus } from "@/types";

/**
 * The first shared nav in this frontend — everything up to now
 * (frontend/app/uploads/page.tsx, frontend/app/page.tsx) has been reached
 * by direct URL, since there was only ever one real "app" page. The
 * dashboard is the second, which makes "move between app sections" a real
 * need — kept deliberately plain (text links, no styling framework) to
 * match this prototype's current minimalism rather than introducing one.
 *
 * "Log out" and "Onboarding" (the account-level actions) live here too, not
 * just on individual pages — previously "Log out" only existed on the
 * onboarding page itself, so every other screen had no way to sign out
 * short of clearing cookies by hand.
 */
export function AppNav({ businessId }: { businessId?: string }) {
  const router = useRouter();
  const suffix = businessId ? `?business=${businessId}` : "";
  const [subscriptionStatus, setSubscriptionStatus] = useState<string | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  // The uploaded company logo (Company Profile "Company logo" section) —
  // shown here too so it's actually visible somewhere besides the one
  // settings page it's uploaded from, per direct feedback. `has_logo` +
  // `updated_at` come off the same GET /businesses/{id} every profile
  // page already calls; `updated_at` doubles as the <img> cache-buster
  // (see frontend/app/onboarding/[id]/page.tsx's identical pattern) so a
  // logo replaced from the profile page doesn't keep showing the old
  // cached image here.
  const [logoInfo, setLogoInfo] = useState<{
    companyName: string;
    logoBusinessId: string | null;
    logoVersion: string | null;
    selectedBusinessName: string;
  } | null>(null);
  // The signed-in member is resolved from the business's existing
  // membership list, rather than guessing from a name in Supabase metadata.
  // That keeps the role accurate for both owners and staff on every page.
  // Shared with frontend/app/welcome/page.tsx, which needs the identical
  // resolution — see useCurrentMember's own docstring.
  const { label: identityLabel } = useCurrentMember(businessId);

  // "Upload data" used to render unconditionally here regardless of the
  // selected business's subscription status — the upload/import routes
  // are correctly 402'd server-side either way, but the link itself
  // implied real access for an unsubscribed (or unpaid branch) business,
  // which is exactly the false impression the onboarding page's own list
  // was already fixed to avoid. Mirrors that same fix here, the one other
  // place a business-scoped "Upload data" link lives.
  useEffect(() => {
    if (!businessId) {
      setSubscriptionStatus(null);
      return;
    }
    apiGet<SubscriptionStatus>(`/businesses/${businessId}/billing/subscription`)
      .then((s) => setSubscriptionStatus(s.status))
      .catch(() => setSubscriptionStatus(null));
  }, [businessId]);

  useEffect(() => {
    if (!businessId) {
      setLogoInfo(null);
      return;
    }
    // A branch change can start a second request before the previous
    // branch's profile request has finished. Only let the active request
    // populate this shared header, otherwise its location can briefly
    // (or permanently, depending on response order) show the old branch.
    let current = true;
    setLogoInfo(null);
    apiGet<Business>(`/businesses/${businessId}`)
      .then(async (selectedBusiness) => {
        // Branches use the parent company's logo when they have not
        // uploaded a separate one. The label always remains the exact
        // selected branch name, matching the page dropdown.
        const logoBusiness =
          selectedBusiness.has_logo || !selectedBusiness.parent_business_id
            ? selectedBusiness
            : await apiGet<Business>(`/businesses/${selectedBusiness.parent_business_id}`).catch(() => null);
        if (current) {
          setLogoInfo({
            companyName: logoBusiness?.name ?? selectedBusiness.name,
            logoBusinessId: logoBusiness?.has_logo ? logoBusiness.id : null,
            logoVersion: logoBusiness?.has_logo ? logoBusiness.updated_at : null,
            selectedBusinessName: businessDisplayLabel(selectedBusiness),
          });
        }
      })
      .catch(() => {
        if (current) setLogoInfo(null);
      });
    return () => {
      current = false;
    };
  }, [businessId]);

  // Notification Centre's unread badge — a lightweight poll (not a
  // websocket/SSE stream, which doesn't exist anywhere in this codebase
  // yet) is enough for a nav badge that only needs to be roughly current,
  // not real-time to the second.
  useEffect(() => {
    if (!businessId) {
      setUnreadCount(0);
      return;
    }
    function refresh() {
      apiGet<{ unread_count: number }>(`/businesses/${businessId}/notifications/unread-count`)
        .then((r) => setUnreadCount(r.unread_count))
        .catch(() => setUnreadCount(0));
    }
    refresh();
    const interval = setInterval(refresh, 60_000);
    // Found live: marking read/dismissing on /notifications updated that
    // page's own count instantly but left this badge showing the old
    // number until the next 60s tick — a real, visible inconsistency
    // (page said 0 unread, nav still said 1). This is a same-tab nudge to
    // poll immediately on a real change, not a push channel — still no
    // WebSockets/SSE.
    const unsubscribe = onNotificationsChanged(refresh);
    return () => {
      clearInterval(interval);
      unsubscribe();
    };
  }, [businessId]);

  // ORLA System status banner (ORLA Notifications/Security/Retention
  // prompt, section 3) — same lightweight-poll pattern as the unread
  // badge above, not a push channel. Independent of whatever page is
  // currently open, so a blocking incident (a stuck/failed report, ORLA
  // insights being down) stays visible everywhere, not just on the
  // Notification Centre itself.
  useEffect(() => {
    if (!businessId) {
      setSystemStatus(null);
      return;
    }
    function refresh() {
      apiGet<SystemStatus>(`/businesses/${businessId}/notifications/system-status`)
        .then(setSystemStatus)
        .catch(() => setSystemStatus(null));
    }
    refresh();
    const interval = setInterval(refresh, 60_000);
    const unsubscribe = onNotificationsChanged(refresh);
    return () => {
      clearInterval(interval);
      unsubscribe();
    };
  }, [businessId]);

  const canUpload = subscriptionStatus === "active";

  async function handleLogout() {
    await supabase?.auth.signOut();
    router.push("/login");
  }

  const activeIncident = systemStatus?.has_active_incident ? systemStatus.incidents[0] : null;

  return (
    <>
      {/* Visible while a blocking incident is active (report_failed/
          report_delayed/import_failed/ai_insights_unavailable) — the
          Notification Centre entry stays as history regardless of this
          banner ("retain the Notification Centre entry as history").
          Shows only the single most recent open incident; the rest are
          still all in the Notification Centre as normal. */}
      {activeIncident && (
        <div role="status" className="app-nav-incident status-warn">
          <span>{activeIncident.title}</span>
          <a href={`/notifications${suffix}`}>
            {systemStatus && systemStatus.incidents.length > 1
              ? `View details (${systemStatus.incidents.length} active)`
              : "View details"}
          </a>
        </div>
      )}
      <nav className="app-nav" aria-label="Main navigation">
        <a className="app-nav__brand" href={`/dashboard${suffix}`} aria-label="ORLA dashboard">
          <span className="app-nav__brand-mark" aria-hidden="true">OR</span>
          <span>ORLA</span>
        </a>
        <div className="app-nav__links">
          <a href={`/dashboard${suffix}`}>Dashboard</a>
      {/* No businessId at all — no business selected yet (e.g. Company
          Profile with no active businesses), nothing real to link to. */}
      {businessId ? (
        canUpload ? (
          <a href={`/uploads${suffix}`}>Upload data</a>
        ) : (
          <span className="app-nav__disabled" title="This shop's subscription isn't active yet">Upload data (subscribe first)</span>
        )
      ) : (
        <a href="/uploads">Upload data</a>
      )}
      <a href={`/reports${suffix}`}>Reports</a>
      <a href={`/chat${suffix}`}>Ask ORLA</a>
      {/* Product-management surfaces (Gaps 1/4/5) — business-scoped like
          Reports/Chat above; nothing to show without a selected business,
          same reasoning as those two. Company Profile (/onboarding) is
          the one page that has no single business of its own, so it
          resolves one itself (its own query param, or the user's first
          active business) and passes it in here — every app-section link
          belongs in this one top nav, never repeated per business row. */}
      {businessId && (
        <>
          <a href={`/products${suffix}`}>Thresholds</a>
          <a href={`/suppliers${suffix}`}>Suppliers</a>
          <a href={`/transactions${suffix}`}>Transactions</a>
        </>
      )}
      {businessId && (
        <>
          <a href={`/notifications${suffix}`}>
            Notifications{unreadCount > 0 ? ` (${unreadCount})` : ""}
          </a>
        </>
      )}
      {/* Global search (notification_staff_filters_global_search_prompt,
          Part 2) — same businessId gate as every other business-scoped
          link above: hidden entirely with no business selected, since
          there'd be nothing to search. Searches only this business/
          branch, never siblings (see GlobalSearchBar's own comment). */}
      {/* No businessId suffix — this links to the full list (every
          business the user owns, active or not), not one specific
          business. Still the same /onboarding route/page (first-run
          creation, billing, shop deletion) — "Company Profile" is a
          clearer label for what it's grown into: also where each
          business's full descriptive profile lives now (per-business
          "View profile" from the list, PATCH /businesses/{id}). */}
      <a href="/onboarding">Company Profile</a>
      {/* Account-level, not business-scoped — same reasoning as Company
          Profile above having no businessId suffix. Login email lives on
          the Supabase Auth identity itself, not any one business. */}
      <a href="/account">Account</a>
        </div>
      {identityLabel && <span className="app-nav__identity">Signed in as {identityLabel}</span>}
      <button className="app-nav__logout" type="button" onClick={handleLogout}>
        Log out
      </button>
      </nav>
      {businessId && (
        <div className="app-nav-search-row">
          <GlobalSearchBar businessId={businessId} />
        </div>
      )}
      {businessId && logoInfo && (
        <div className="app-business-header" aria-label="Current business">
          {logoInfo.logoBusinessId && logoInfo.logoVersion && (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element -- public API logo URL, not a Next-managed asset. */}
              <img
                src={`${API_URL}/businesses/${logoInfo.logoBusinessId}/logo?v=${encodeURIComponent(logoInfo.logoVersion)}`}
                alt=""
                aria-hidden="true"
                className="app-business-header__logo"
              />
            </>
          )}
          <div>
            <span className="app-business-header__eyebrow">Current business</span>
            <strong>{logoInfo.companyName}</strong>
            <span className="app-business-header__meta">{logoInfo.selectedBusinessName}</span>
          </div>
        </div>
      )}
    </>
  );
}
