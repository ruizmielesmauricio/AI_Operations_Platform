"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api/client";
import type { AddressSuggestion } from "@/types";

// Debounced after typing stops, and only once there's enough text to
// plausibly match something — keeps request volume reasonable against
// Geoapify's free-tier cap without needing a manual trigger.
const ADDRESS_SUGGEST_DEBOUNCE_MS = 350;
const ADDRESS_SUGGEST_MIN_CHARS = 3;

/**
 * Live, as-you-type address suggestions (GET /businesses/{business_id}/
 * address-suggestions, backed by Geoapify Autocomplete). Extracted from
 * frontend/app/onboarding/[id]/page.tsx, which had this same debounce/
 * dropdown/apply-suggestion logic inlined, once the branch-creation form
 * in frontend/app/onboarding/page.tsx needed the identical behavior a
 * second time.
 *
 * `businessId` is only ever used for the endpoint's own membership gate
 * (app/api/businesses.py::get_address_suggestions — the suggestions
 * themselves aren't scoped to any one business's data) — safe to pass a
 * different, already-existing business's id (e.g. the parent shop, while
 * drafting a not-yet-created branch's profile) as long as the caller is
 * a member of it. Pass `null` to disable lookups entirely (e.g. before a
 * parent id is known).
 */
export function useAddressAutocomplete(businessId: string | null) {
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  function handleAddressChange(value: string) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!businessId || value.trim().length < ADDRESS_SUGGEST_MIN_CHARS) {
      setSuggestions([]);
      setSuggestOpen(false);
      return;
    }
    debounceRef.current = setTimeout(() => {
      setSuggestLoading(true);
      apiGet<AddressSuggestion[]>(
        `/businesses/${businessId}/address-suggestions?text=${encodeURIComponent(value)}`
      )
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

  function openIfHasSuggestions() {
    if (suggestions.length > 0) setSuggestOpen(true);
  }

  function closeSoon() {
    // A short delay, not an immediate close — a direct blur-then-click on
    // a suggestion would otherwise close the dropdown before the click's
    // own handler ever fires.
    setTimeout(() => setSuggestOpen(false), 150);
  }

  function reset() {
    setSuggestions([]);
    setSuggestOpen(false);
  }

  return { suggestions, suggestOpen, suggestLoading, handleAddressChange, openIfHasSuggestions, closeSoon, reset };
}
