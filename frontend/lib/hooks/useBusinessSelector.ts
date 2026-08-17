"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api/client";
import type { Business } from "@/types";

/**
 * Loads the current user's businesses and picks one to work with, honoring
 * a `?business=<id>` query param when present (so a link from one page can
 * carry the selection to another) and otherwise defaulting to the first.
 * Extracted from frontend/app/uploads/page.tsx, which had this same ~10
 * lines inlined — the dashboard needing the identical behavior a second
 * time is the point to share it instead of copying it again.
 *
 * Only runs once `session` is truthy — pass the `session` from
 * useRequireSession so this never fires an unauthenticated request.
 */
export function useBusinessSelector(session: unknown) {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [businessId, setBusinessId] = useState<string>("");
  // False until the first fetch settles (success or failure) — added for
  // frontend/app/welcome/page.tsx, which redirects when `businesses` is
  // empty and needs to tell "still loading" apart from "genuinely zero
  // businesses" to avoid a flash-redirect for an account that does have
  // one. Every existing caller ignores this field, so it's additive only.
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!session) return;
    apiGet<Business[]>("/businesses")
      .then((rows) => {
        setBusinesses(rows);
        const requested = new URLSearchParams(window.location.search).get("business");
        const preselect = rows.find((b) => b.id === requested)?.id;
        setBusinessId((current) => current || preselect || rows[0]?.id || "");
      })
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, [session]);

  return { businesses, businessId, setBusinessId, loaded };
}
