"use client";

import { useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiGet, apiPatch } from "@/lib/api/client";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { ProductThreshold } from "@/types";

// Gap 1 — low-stock threshold UI + a deterministic recommendation.
// ORLA/AI is never in this loop: recommendation.recommended_threshold_days
// already comes fully computed from the backend (app/analytics/
// replenishment.py) — this page only displays and applies it. Owner/
// manager can edit; any role can view (mirrors suppliers/employee seats).
export default function ProductThresholdsPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);
  const business = businesses.find((b) => b.id === businessId);
  const canWrite = business?.role === "owner" || business?.role === "manager";

  const [rows, setRows] = useState<ProductThreshold[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);

  function load(id: string) {
    setLoading(true);
    setError(null);
    apiGet<ProductThreshold[]>(`/businesses/${id}/products/thresholds`)
      .then(setRows)
      .catch(() => setError("Could not load products."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (businessId) load(businessId);
  }, [businessId]);

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
      setNotice(`Saved threshold for "${productName}".`);
      load(businessId);
    } catch {
      setError(`Could not save the threshold for "${productName}". Try again.`);
    } finally {
      setSavingId(null);
    }
  }

  if (checkingSession) return <p>Loading…</p>;

  return (
    <main>
      <AppNav businessId={businessId} />
      <h1>Low-stock thresholds</h1>
      <p className="hint">
        A product is flagged as low-stock once its stock cover drops below this many days. Recommended values are
        computed from your recorded supplier lead times (plus a 3-day safety buffer) when known, or a general
        default otherwise — ORLA never invents this number, it only explains it.
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

      {!loading && businessId && (
        <table>
          <thead>
            <tr>
              <th>Product</th>
              <th>Stock on hand</th>
              <th>Sells (last 30 days)</th>
              <th>Current threshold</th>
              <th>Recommended</th>
              {canWrite && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.product_id}>
                <td>
                  {row.name}
                  {row.category_name && <span className="hint"> ({row.category_name})</span>}
                </td>
                <td>{row.stock_on_hand}</td>
                <td>
                  {row.insufficient_data
                    ? "not enough sales history yet"
                    : `${row.units_sold_in_period} units${row.cover_days !== null ? ` (~${row.cover_days}d cover)` : ""}`}
                </td>
                <td>
                  {editingId === row.product_id ? (
                    <input
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      style={{ width: "5em" }}
                    />
                  ) : (
                    <>
                      {row.effective_threshold_days}d
                      {row.product_threshold_days === null && <span className="hint"> (inherited)</span>}
                    </>
                  )}
                </td>
                <td>
                  {row.recommendation.recommended_threshold_days}d
                  <span
                    className="hint"
                    title={
                      row.recommendation.basis === "supplier_lead_time"
                        ? `Based on a ${row.recommendation.lead_time_days}-day supplier lead time + ${row.recommendation.safety_buffer_days}-day safety buffer.`
                        : "No supplier lead time recorded yet for this product — showing the general default. Add one on the Suppliers page to get a product-specific recommendation."
                    }
                  >
                    {" "}
                    ({row.recommendation.basis === "supplier_lead_time" ? "from supplier lead time" : "default"})
                  </span>
                </td>
                {canWrite && (
                  <td>
                    {editingId === row.product_id ? (
                      <>
                        <button
                          type="button"
                          disabled={savingId === row.product_id}
                          onClick={() => handleSave(row.product_id, row.name, editValue, false)}
                        >
                          Save
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
                        {row.effective_threshold_days !== row.recommendation.recommended_threshold_days && (
                          <button
                            type="button"
                            disabled={savingId === row.product_id}
                            onClick={() => handleSave(row.product_id, row.name, row.recommendation.recommended_threshold_days, true)}
                          >
                            Accept recommendation
                          </button>
                        )}
                      </>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
