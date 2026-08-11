"use client";

import { useMemo, useRef, useState } from "react";
import { formatMoney } from "@/lib/format";
import { SEARCH_MIN_CHARS, useGlobalSearch } from "@/lib/hooks/useGlobalSearch";
import type { GlobalSearchResult } from "@/types";

// One flat, keyboard-navigable, ordered list underneath the five grouped
// sections — Enter/ArrowUp/ArrowDown need a single linear order to move
// through regardless of which group a result is in, and the group label
// is carried right on each row so the same array both drives keyboard
// navigation and renders the grouped panel, instead of two separate
// data shapes that could drift out of sync with each other.
interface FlatResult {
  key: string;
  group: string;
  href: string;
  label: string;
  sublabel?: string;
}

function buildHref(businessId: string, path: string, extra?: Record<string, string>): string {
  const params = new URLSearchParams({ business: businessId, ...extra });
  return `${path}?${params.toString()}`;
}

function flattenResults(results: GlobalSearchResult | null, businessId: string): FlatResult[] {
  if (!results) return [];
  const rows: FlatResult[] = [];
  for (const p of results.products) {
    rows.push({
      key: `product-${p.id}`,
      group: "Products",
      href: buildHref(businessId, "/products"),
      label: p.name,
      sublabel:
        [p.sku, p.category_name, p.current_stock !== null ? `${p.current_stock} in stock` : null]
          .filter(Boolean)
          .join(" · ") || undefined,
    });
  }
  for (const s of results.sales) {
    rows.push({
      key: `sale-${s.id}`,
      group: "Sales",
      href: buildHref(businessId, "/transactions", {
        type: "sales",
        ...(s.product_id ? { product_id: s.product_id } : {}),
      }),
      label: s.order_reference ?? s.product_name ?? "Sale",
      sublabel: `${s.product_name ?? "Unknown product"} · ${formatMoney(s.line_total)}`,
    });
  }
  for (const p of results.purchases) {
    rows.push({
      key: `purchase-${p.id}`,
      group: "Purchases",
      href: buildHref(businessId, "/transactions", {
        type: "purchases",
        ...(p.product_id ? { product_id: p.product_id } : {}),
      }),
      label: p.purchase_reference ?? p.product_name ?? "Purchase",
      sublabel: [p.product_name, p.supplier_name].filter(Boolean).join(" · ") || undefined,
    });
  }
  for (const s of results.suppliers) {
    rows.push({
      key: `supplier-${s.id}`,
      group: "Suppliers",
      href: buildHref(businessId, "/suppliers"),
      label: s.name,
      sublabel: s.contact_info ?? undefined,
    });
  }
  for (const r of results.repairs) {
    rows.push({
      key: `repair-${r.id}`,
      group: "Repairs",
      href: buildHref(businessId, "/transactions", { type: "repairs" }),
      label: r.repair_reference ?? r.description ?? "Repair",
      sublabel: r.repair_reference ? (r.description ?? undefined) : undefined,
    });
  }
  return rows;
}

/**
 * Global search bar (Part 2 of the notification_staff_filters_global_
 * search prompt) — lives in AppNav, next to the other top-nav links, so
 * it's available wherever a business is selected (mirrors every other
 * business-scoped nav link's own `businessId &&` gate). Searches only
 * `membership.business_id` server-side (GET /businesses/{id}/search) —
 * never sibling branches, same tenant boundary as everything else in
 * this nav.
 */
export function GlobalSearchBar({ businessId }: { businessId: string }) {
  const { query, results, loading, error, open, setOpen, handleQueryChange, reset } = useGlobalSearch(businessId);
  const [highlighted, setHighlighted] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  const flat = useMemo(() => flattenResults(results, businessId), [results, businessId]);
  const showDropdown = open && query.trim().length >= SEARCH_MIN_CHARS;

  // A full navigation (window.location.href), not next/navigation's
  // router.push — matching AppNav's own <a href> links (every other
  // cross-page link in this frontend is a plain anchor, never a client-
  // side transition). Confirmed live: router.push here left
  // frontend/app/transactions/page.tsx showing its default Sales tab
  // instead of the requested type, because that page reads
  // window.location.search once at initial render rather than reacting
  // to a client-side URL change — a real, pre-existing gap in that page,
  // not something to silently paper over by reaching into a file outside
  // this feature. A full navigation always lands with the right query
  // params already in place, and matches the rest of this nav besides.
  function navigateTo(href: string) {
    reset();
    setHighlighted(-1);
    window.location.href = href;
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      reset();
      setHighlighted(-1);
      inputRef.current?.blur();
      return;
    }
    if (!showDropdown || flat.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => (i + 1) % flat.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => (i <= 0 ? flat.length - 1 : i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = highlighted >= 0 ? flat[highlighted] : flat[0];
      if (target) navigateTo(target.href);
    }
  }

  // Grouped for display (same fixed order as flattenResults), each row
  // paired with its real index into `flat` (via map, not a second
  // indexOf lookup — flat has no duplicate keys, but this avoids relying
  // on that) so highlighting stays correct across both.
  const groups: { title: string; rows: { row: FlatResult; index: number }[] }[] = [];
  for (const title of ["Products", "Sales", "Purchases", "Suppliers", "Repairs"]) {
    const rows = flat
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => row.group === title);
    if (rows.length > 0) groups.push({ title, rows });
  }

  return (
    <span className="global-search">
      <input
        ref={inputRef}
        type="search"
        placeholder="Search…"
        aria-label="Search products, sales, purchases, suppliers, repairs"
        value={query}
        onChange={(e) => {
          handleQueryChange(e.target.value);
          setHighlighted(-1);
        }}
        onKeyDown={handleKeyDown}
        onFocus={() => {
          if (query.trim().length >= SEARCH_MIN_CHARS) setOpen(true);
        }}
        // Same short delay as useAddressAutocomplete.ts's closeSoon — a
        // direct blur-then-click on a result would otherwise close this
        // dropdown before the click's own navigation ever fires.
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="global-search__input"
      />
      {showDropdown && (
        <div
          className="global-search__results"
        >
          {loading && (
            <p className="hint" style={{ margin: "0 0.75em" }}>
              Searching…
            </p>
          )}
          {!loading && error && (
            <p className="hint status-error" style={{ margin: "0 0.75em" }}>
              {error}
            </p>
          )}
          {!loading && !error && flat.length === 0 && (
            <p className="hint" style={{ margin: "0 0.75em" }}>
              No results for &ldquo;{query.trim()}&rdquo;.
            </p>
          )}
          {!loading &&
            !error &&
            groups.map((g) => (
              <div key={g.title} style={{ marginBottom: "0.4em" }}>
                <div
                  style={{
                    fontSize: "0.75em",
                    fontWeight: "bold",
                    color: "#57606a",
                    padding: "0.15em 0.75em",
                    textTransform: "uppercase",
                  }}
                >
                  {g.title}
                </div>
                {g.rows.map(({ row, index }) => (
                  <button
                    key={row.key}
                    type="button"
                    // Mousedown, not click — fires before the input's own
                    // onBlur closes the dropdown, so a click on a result
                    // still lands (belt and braces alongside the onBlur
                    // delay above, since a fast click can otherwise race
                    // the timeout).
                    onMouseDown={(e) => {
                      e.preventDefault();
                      navigateTo(row.href);
                    }}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "0.3em 0.75em",
                      border: "none",
                      background: index === highlighted ? "Highlight" : "transparent",
                      color: index === highlighted ? "HighlightText" : "inherit",
                      cursor: "pointer",
                    }}
                  >
                    <div>{row.label}</div>
                    {row.sublabel && (
                      <div className="hint" style={{ margin: 0, color: index === highlighted ? "HighlightText" : undefined }}>
                        {row.sublabel}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            ))}
        </div>
      )}
    </span>
  );
}
