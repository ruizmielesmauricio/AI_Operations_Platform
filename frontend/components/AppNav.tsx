"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet } from "@/lib/api/client";
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

  const canUpload = subscriptionStatus === "active";

  async function handleLogout() {
    await supabase?.auth.signOut();
    router.push("/login");
  }

  return (
    <nav>
      <a href={`/dashboard${suffix}`}>Dashboard</a>
      {" · "}
      {/* No businessId at all (onboarding) — nothing to link to yet,
          onboarding's own per-business list already has the real,
          correctly-gated links. */}
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
      {/* No businessId suffix — onboarding lists every business the user
          owns, not one specific business. Previously unreachable from
          here at all once a user had ≥1 business (only linked from each
          page's empty "no business yet" state) — this is also now where
          billing management and shop deletion live, not just first-run
          creation. */}
      <a href="/onboarding">Onboarding</a>
      {" · "}
      <button type="button" onClick={handleLogout}>
        Log out
      </button>
    </nav>
  );
}
