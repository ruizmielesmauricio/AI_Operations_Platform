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

  useEffect(() => {
    if (!session) return;
    apiGet<Business[]>("/businesses")
      .then((rows) => {
        setBusinesses(rows);
        const requested = new URLSearchParams(window.location.search).get("business");
        const preselect = rows.find((b) => b.id === requested)?.id;
        setBusinessId((current) => current || preselect || rows[0]?.id || "");
      })
      .catch(() => undefined);
  }, [session]);

  return { businesses, businessId, setBusinessId };
}
