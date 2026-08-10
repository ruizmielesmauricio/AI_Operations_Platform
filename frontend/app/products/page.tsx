"use client";

import { useEffect, useMemo, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiGet, apiPatch } from "@/lib/api/client";
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

export default function ProductThresholdsPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);
  const business = businesses.find((b) => b.id === businessId);
  const canWrite = business?.role === "owner" || business?.role === "manager";

  const [rows, setRows] = useState<ProductThreshold[]>([]);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [forecastByProductId, setForecastByProductId] = useState<Record<string, number>>({});
  const [categoryId, setCategoryId] = useState("");
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

  const visibleRows = useMemo(
    () => (categoryId ? rows.filter((r) => r.category_id === categoryId) : rows),
    [rows, categoryId]
  );

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
      <p className="hint">
        Each column answers a different question: <strong>In stock</strong> — how many units are there now?{" "}
        <strong>Sold last 30 days</strong> — how quickly is it selling? <strong>Stock cover</strong> — roughly how
        many days will current stock last? <strong>Reorder point</strong> — when should ORLA warn me (in days of
        cover)? <strong>ORLA recommends</strong> — what does ORLA think the reorder point should be?{" "}
        <strong>Setting</strong> — where did the current value come from? Recommendations come from your recorded
        supplier lead times (plus a 3-day safety buffer) when known, or a general default otherwise — ORLA never
        invents this number, it only explains it.
      </p>

      <label htmlFor="business-select">Shop</label>
      <br />
      <select id="business-select" value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
        {businesses.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>

      {error && <p className="status-error">{error}</p>}
      {notice && <p className="status-ok">{notice}</p>}
      {loading && <p>Loading…</p>}

      {!loading && businessId && rows.length > 0 && (
        <ul>
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
        <section>
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
        </div>
      )}

      {!loading && businessId && visibleRows.length === 0 && (
        <p>{rows.length === 0 ? "No products yet." : "No products match this category."}</p>
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
