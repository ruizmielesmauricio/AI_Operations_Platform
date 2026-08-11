"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet } from "@/lib/api/client";
import { onNotificationsChanged } from "@/lib/notificationsBus";
import { supabase } from "@/lib/supabase/client";
import type { SubscriptionStatus } from "@/types";

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

  const canUpload = subscriptionStatus === "active";

  async function handleLogout() {
    await supabase?.auth.signOut();
    router.push("/login");
  }

  return (
    <nav>
      <a href={`/dashboard${suffix}`}>Dashboard</a>
      {" · "}
      {/* No businessId at all — no business selected yet (e.g. Company
          Profile with no active businesses), nothing real to link to. */}
      {businessId ? (
        canUpload ? (
          <a href={`/uploads${suffix}`}>Upload data</a>
        ) : (
          <span title="This shop's subscription isn't active yet">Upload data (subscribe first)</span>
        )
      ) : (
        <a href="/uploads">Upload data</a>
      )}
      {" · "}
      <a href={`/reports${suffix}`}>Reports</a>
      {" · "}
      <a href={`/chat${suffix}`}>Ask ORLA</a>
      {" · "}
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
          {" · "}
          <a href={`/suppliers${suffix}`}>Suppliers</a>
          {" · "}
          <a href={`/transactions${suffix}`}>Transactions</a>
          {" · "}
        </>
      )}
      {businessId && (
        <>
          <a href={`/notifications${suffix}`}>
            Notifications{unreadCount > 0 ? ` (${unreadCount})` : ""}
          </a>
          {" · "}
        </>
      )}
      {/* No businessId suffix — this links to the full list (every
          business the user owns, active or not), not one specific
          business. Still the same /onboarding route/page (first-run
          creation, billing, shop deletion) — "Company Profile" is a
          clearer label for what it's grown into: also where each
          business's full descriptive profile lives now (per-business
          "View profile" from the list, PATCH /businesses/{id}). */}
      <a href="/onboarding">Company Profile</a>
      {" · "}
      <button type="button" onClick={handleLogout}>
        Log out
      </button>
    </nav>
  );
}
