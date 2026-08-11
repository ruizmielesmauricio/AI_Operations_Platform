"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api/client";
import type { GlobalSearchResult } from "@/types";

// Mirrors app/application/search.py's own MIN_QUERY_LENGTH/DEFAULT_LIMIT_
// PER_GROUP exactly — kept as a second literal (not fetched from the
// backend) since it only ever needs to match the same, effectively fixed
// constant, and duplicating one small number here is simpler than a
// round-trip to learn it. Debounce follows the same
// useAddressAutocomplete.ts precedent (350ms), same reasoning: enough
// text has usually landed before the timer fires, without needing a
// manual "search" button.
export const SEARCH_MIN_CHARS = 2;
const SEARCH_DEBOUNCE_MS = 300;

/**
 * Debounced global search (GET /businesses/{business_id}/search?q=...),
 * scoped to whichever business/branch is currently selected in the nav —
 * never sibling branches, since the backend route itself resolves the
 * search to `membership.business_id` only (see app/api/search.py).
 * Extracted as its own hook, not inlined in GlobalSearchBar, so the
 * debounce/request-race handling has the exact same shape as
 * useAddressAutocomplete.ts rather than a second, subtly different copy.
 */
export function useGlobalSearch(businessId: string | undefined) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GlobalSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guards against an earlier, slower request's response landing after a
  // later one's and clobbering it — the classic race a debounce alone
  // doesn't prevent (the timer only delays when a request starts, not
  // how long it takes to come back).
  const requestSeq = useRef(0);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  function handleQueryChange(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = value.trim();
    if (!businessId || trimmed.length < SEARCH_MIN_CHARS) {
      setResults(null);
      setLoading(false);
      setError(null);
      setOpen(false);
      return;
    }
    setOpen(true);
    debounceRef.current = setTimeout(() => {
      const seq = ++requestSeq.current;
      setLoading(true);
      setError(null);
      apiGet<GlobalSearchResult>(`/businesses/${businessId}/search?q=${encodeURIComponent(trimmed)}`)
        .then((data) => {
          if (seq !== requestSeq.current) return;
          setResults(data);
        })
        .catch(() => {
          if (seq !== requestSeq.current) return;
          setResults(null);
          setError("Search failed — try again.");
        })
        .finally(() => {
          if (seq === requestSeq.current) setLoading(false);
        });
    }, SEARCH_DEBOUNCE_MS);
  }

  function reset() {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setQuery("");
    setResults(null);
    setLoading(false);
    setError(null);
    setOpen(false);
  }

  return { query, results, loading, error, open, setOpen, handleQueryChange, reset };
}
