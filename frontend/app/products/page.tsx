"use client";

import { useEffect, useMemo, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiGet, apiPatch } from "@/lib/api/client";
import { businessDisplayLabel } from "@/lib/businessLabel";
import { formatDays } from "@/lib/format";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { Forecast, ProductCategory, ProductThreshold } from "@/types";

// Recommended Restock reuses Stage C13's existing forecast engine's
// suggested_reorder_quantity (confidence band's high end minus current
// stock, over this horizon) rather than a cruder day-count formula —
// it's the only quantity-in-units figure this app already computes
// deterministically. 14 days is a fixed, documented default (not tied to
// any one product's own lead time) — long enough to be a useful starting
// order size, short enough not to over-order for a fast-moving item.
const _RESTOCK_FORECAST_HORIZON_DAYS = 14;

// Gap 1 — Product Reorder Rules: low-stock threshold UI + a deterministic
// recommendation. ORLA/AI is never in this loop: recommendation.
// recommended_threshold_days already comes fully computed from the
// backend (app/analytics/replenishment.py) — this page only displays and
// applies it. Owner/manager can edit; any role can view (mirrors
// suppliers/employee seats).
//
// "Reorder point" here is measured in days of stock cover (flag once
// cover drops below this many days), not a raw unit count — the
// established, already-tested metric behind the low-stock alert system
// (Stage C12). The table makes that unit explicit in every cell rather
// than leaving "6" ambiguous between days and units.

function settingLabel(row: ProductThreshold): string {
  if (row.product_threshold_days !== null) {
    return row.product_threshold_source === "orla_recommended" ? "ORLA recommended" : "Product custom";
  }
  return row.category_threshold_days !== null ? "Category default" : "System default";
}

// Deep-link target for the weekly Stock Review notification's single
// action link (backend/app/application/notifications.py::notify_stock_
// review, ?stock_filter=out_of_stock|stale|excess on this page's own
// URL). The two thresholds below must stay in sync with backend/app/
// analytics/stock_review.py's own SLOW_MOVER_MIN_COVER_DAYS (imported
// from retail.py) and EXCESS_STOCK_COVER_MULTIPLIER — duplicated here
// rather than fetched, same precedent as every other backend-Literal
// mirrored into a frontend constant in this codebase (e.g.
// NotificationCategoryFilter).
const STOCK_FILTER_LABELS: Record<string, string> = {
  out_of_stock: "Out of stock",
  stale: "Stale",
  excess: "Overstocked",
};
const SLOW_MOVER_MIN_COVER_DAYS = 60;
const EXCESS_STOCK_COVER_MULTIPLIER = 3;

function matchesStockFilter(row: ProductThreshold, filter: string): boolean {
  if (filter === "out_of_stock") return row.stock_on_hand <= 0;
  if (filter === "stale") {
    // Dead stock (real stock on hand, zero sales this lookback window —
    // cover_days is null exactly in that case) or a known slow mover.
    if (row.cover_days === null) return row.stock_on_hand > 0;
    return Number(row.cover_days) >= SLOW_MOVER_MIN_COVER_DAYS;
  }
  if (filter === "excess") {
    if (row.cover_days === null) return false; // no real sales evidence to judge "too much" against
    return Number(row.cover_days) >= Number(row.effective_threshold_days) * EXCESS_STOCK_COVER_MULTIPLIER;
  }
  return true;
}

export default function ProductThresholdsPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);
  const business = businesses.find((b) => b.id === businessId);
  const canWrite = business?.role === "owner" || business?.role === "manager";

  const [rows, setRows] = useState<ProductThreshold[]>([]);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [forecastByProductId, setForecastByProductId] = useState<Record<string, number>>({});
  const [categoryId, setCategoryId] = useState("");
  // Deep-linked from the weekly Stock Review notification
  // (?stock_filter=out_of_stock|stale|excess) — same initial-URL-read
  // pattern as frontend/app/transactions/page.tsx's own txType.
  const initialStockFilter =
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("stock_filter") ?? "" : "";
  const [stockFilter, setStockFilter] = useState(initialStockFilter);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);

  function load(id: string) {
    setLoading(true);
    setError(null);
    Promise.all([
      apiGet<ProductThreshold[]>(`/businesses/${id}/products/thresholds`),
      apiGet<ProductCategory[]>(`/businesses/${id}/product-categories`),
    ])
      .then(([thresholds, cats]) => {
        setRows(thresholds);
        setCategories(cats);
      })
      .catch(() => setError("Could not load products."))
      .finally(() => setLoading(false));

    // Fetched and failed independently of the table above — Recommended
    // Restock is a secondary enhancement (a reorder quantity suggestion
    // on top of rows the table can already show without it); a forecast
    // hiccup must never block the reorder-rules table itself from
    // loading. A failure here just leaves quantities unavailable, not an
    // error banner.
    apiGet<Forecast>(`/businesses/${id}/analytics/forecast?horizon_days=${_RESTOCK_FORECAST_HORIZON_DAYS}`)
      .then((forecast) =>
        setForecastByProductId(
          Object.fromEntries(forecast.products.map((p) => [p.product_id, p.suggested_reorder_quantity]))
        )
      )
      .catch(() => setForecastByProductId({}));
  }

  useEffect(() => {
    if (businessId) load(businessId);
  }, [businessId]);

  const visibleRows = useMemo(() => {
    let filtered = categoryId ? rows.filter((r) => r.category_id === categoryId) : rows;
    if (stockFilter) filtered = filtered.filter((r) => matchesStockFilter(r, stockFilter));
    return filtered;
  }, [rows, categoryId, stockFilter]);

  // Recommended Restock — "below reorder point" means current stock
  // cover (in days) has dropped below the active reorder point (also in
  // days); the two are the same unit, unlike a raw stock-count vs. a
  // day-count threshold, which can't be compared directly. Scoped to
  // visibleRows (the category-filtered set) per the requirement that
  // this section respect the same category filter as the table below.
  const restockRows = useMemo(
    () =>
      visibleRows.filter(
        (r) => r.cover_days !== null && Number(r.cover_days) < Number(r.effective_threshold_days)
      ),
    [visibleRows]
  );

  // Deterministic counts over whatever backend data is already loaded —
  // no AI, no new calculation, just aggregating fields the API already
  // returned. Computed over the full (unfiltered) catalogue, independent
  // of the category filter above, so the headline insights always
  // reflect the whole shop even while the table itself is narrowed down.
  const insights = useMemo(() => {
    const belowReorderPoint = rows.filter(
      (r) => r.cover_days !== null && Number(r.cover_days) < Number(r.effective_threshold_days)
    ).length;
    const orlaRecommendsRaising = rows.filter(
      (r) => Number(r.recommendation.recommended_threshold_days) > Number(r.effective_threshold_days)
    ).length;
    const needsMoreHistory = rows.filter((r) => r.insufficient_data).length;
    return { belowReorderPoint, orlaRecommendsRaising, needsMoreHistory };
  }, [rows]);

  async function handleSave(productId: string, productName: string, value: string, acceptedRecommendation: boolean) {
    setSavingId(productId);
    setError(null);
    setNotice(null);
    try {
      await apiPatch(`/businesses/${businessId}/products/${productId}/threshold`, {
        threshold_days: value === "" ? null : value,
        accepted_recommendation: acceptedRecommendation,
      });
      setEditingId(null);
      setNotice(`Saved reorder point for "${productName}".`);
      load(businessId);
    } catch {
      setError(`Could not save the reorder point for "${productName}". Try again.`);
    } finally {
      setSavingId(null);
    }
  }

  if (checkingSession) return <p>Loading…</p>;

  return (
    <main>
      <AppNav businessId={businessId} />
      <h1>Product Reorder Rules</h1>
      <section className="threshold-guide" aria-label="How reorder rules work">
        <div>
          <strong>In stock</strong>
          <span>Units available now.</span>
        </div>
        <div>
          <strong>Sold last 30 days</strong>
          <span>How quickly the product is moving.</span>
        </div>
        <div>
          <strong>Stock cover</strong>
          <span>Estimated days the current stock will last.</span>
        </div>
        <div>
          <strong>Reorder point</strong>
          <span>When ORLA should warn you.</span>
        </div>
        <div>
          <strong>ORLA recommends</strong>
          <span>A suggested reorder point from your sales and supplier lead time.</span>
        </div>
        <div>
          <strong>Setting</strong>
          <span>Whether the value is custom, category-based, or recommended.</span>
        </div>
      </section>

      <label htmlFor="business-select">Shop</label>
      <br />
      <select id="business-select" value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
        {businesses.map((b) => (
          <option key={b.id} value={b.id}>
            {businessDisplayLabel(b)}
          </option>
        ))}
      </select>

      {error && <p className="status-error">{error}</p>}
      {notice && <p className="status-ok">{notice}</p>}
      {loading && <p>Loading…</p>}

      {!loading && businessId && rows.length > 0 && (
        <ul className="threshold-insights">
          {insights.belowReorderPoint > 0 && (
            <li>
              {insights.belowReorderPoint} product{insights.belowReorderPoint === 1 ? " is" : "s are"} below{" "}
              {insights.belowReorderPoint === 1 ? "its" : "their"} reorder point.
            </li>
          )}
          {insights.orlaRecommendsRaising > 0 && (
            <li>ORLA recommends raising reorder points for {insights.orlaRecommendsRaising} fast-moving products.</li>
          )}
          {insights.needsMoreHistory > 0 && (
            <li>{insights.needsMoreHistory} products need more sales history before ORLA can recommend a rule.</li>
          )}
        </ul>
      )}

      {!loading && businessId && rows.length > 0 && (
        <section className="threshold-restock">
          <h2>Recommended Restock</h2>
          {restockRows.length === 0 ? (
            <p>No products are below their reorder point.</p>
          ) : (
            <ul>
              {restockRows.map((row) => {
                const quantity = forecastByProductId[row.product_id];
                const coverDays = formatDays(row.cover_days as string);
                const thresholdDays = formatDays(row.effective_threshold_days);
                return (
                  <li key={row.product_id}>
                    {quantity !== undefined && quantity > 0
                      ? `Order ${quantity} more unit${quantity === 1 ? "" : "s"} of ${row.name}. `
                      : `${row.name} needs restocking. `}
                    Current stock is {row.stock_on_hand} and the reorder point is {thresholdDays}d ({coverDays}d of
                    cover left, selling {row.units_sold_in_period} in the last 30 days).
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {!loading && businessId && (
        <div>
          <label htmlFor="category-filter">Category</label>{" "}
          <select
            id="category-filter"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            disabled={categories.length === 0}
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          {" "}
          <label htmlFor="stock-filter">Stock status</label>{" "}
          <select id="stock-filter" value={stockFilter} onChange={(e) => setStockFilter(e.target.value)}>
            <option value="">All products</option>
            {Object.entries(STOCK_FILTER_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      )}

      {!loading && businessId && visibleRows.length === 0 && (
        <p>
          {rows.length === 0
            ? "No products yet."
            : `No products match ${categoryId && stockFilter ? "this category and status" : categoryId ? "this category" : "this status"}.`}
        </p>
      )}

      {!loading && businessId && visibleRows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th title="How many units are there now?">In stock</th>
                <th title="How quickly is it selling?">Sold last 30 days</th>
                <th title="Roughly how many days will current stock last?">Stock cover</th>
                <th title="When should ORLA warn me? (days of cover)">Reorder point</th>
                <th title="What does ORLA think the reorder point should be?">ORLA recommends</th>
                <th title="Where did the current value come from?">Setting</th>
                {canWrite && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => {
                const recommendedDays = formatDays(row.recommendation.recommended_threshold_days);
                const hasDifferentRecommendation =
                  row.effective_threshold_days !== row.recommendation.recommended_threshold_days;
                return (
                  <tr key={row.product_id}>
                    <td>
                      {row.name}
                      {row.category_name && <span className="hint"> ({row.category_name})</span>}
                    </td>
                    <td>{row.stock_on_hand}</td>
                    <td>
                      {row.insufficient_data ? "not enough sales history yet" : `${row.units_sold_in_period} units`}
                    </td>
                    <td>{row.cover_days !== null ? `~${formatDays(row.cover_days)}d` : "—"}</td>
                    <td>
                      {editingId === row.product_id ? (
                        <input
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          style={{ width: "5em" }}
                          aria-label={`Reorder point for ${row.name} (days)`}
                        />
                      ) : (
                        `${formatDays(row.effective_threshold_days)}d`
                      )}
                    </td>
                    <td
                      title={
                        row.recommendation.basis === "supplier_lead_time"
                          ? `Based on a ${formatDays(row.recommendation.lead_time_days ?? "0")}-day supplier lead time + ${formatDays(row.recommendation.safety_buffer_days)}-day safety buffer.`
                          : "No supplier lead time recorded yet for this product — showing the general default. Add one on the Suppliers page to get a product-specific recommendation."
                      }
                    >
                      {recommendedDays}d
                      <span className="hint">
                        {" "}
                        ({row.recommendation.basis === "supplier_lead_time" ? "from supplier lead time" : "default"})
                      </span>
                    </td>
                    <td>{settingLabel(row)}</td>
                    {canWrite && (
                      <td>
                        <div className="product-table-actions">
                        {editingId === row.product_id ? (
                          <>
                            <button
                              type="button"
                              disabled={savingId === row.product_id}
                              onClick={() => handleSave(row.product_id, row.name, editValue, false)}
                            >
                              Save reorder point
                            </button>{" "}
                            <button type="button" onClick={() => setEditingId(null)}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={() => {
                                setEditingId(row.product_id);
                                setEditValue(row.product_threshold_days ?? row.effective_threshold_days);
                              }}
                            >
                              Edit
                            </button>{" "}
                            {/* Distinct wording from the manual Save action above — this one only
                                ever applies ORLA's own suggested value verbatim, never a typed-in
                                number, so it reads as "adopt ORLA's suggestion," not a second,
                                confusingly-worded way to set an arbitrary value. */}
                            {hasDifferentRecommendation && (
                              <button
                                className="product-recommendation-button"
                                type="button"
                                disabled={savingId === row.product_id}
                                onClick={() =>
                                  handleSave(
                                    row.product_id, row.name, row.recommendation.recommended_threshold_days, true
                                  )
                                }
                              >
                                {`Use ORLA's ${recommendedDays}d recommendation`}
                              </button>
                            )}
                          </>
                        )}
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
