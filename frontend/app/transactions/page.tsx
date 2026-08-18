"use client";

import { useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiGet } from "@/lib/api/client";
import { businessDisplayLabel } from "@/lib/businessLabel";
import { formatMoney } from "@/lib/format";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { PaginatedResult, PurchaseTransaction, RepairTransaction, SaleTransaction } from "@/types";

// Gap 5 — raw transaction drill-down behind a dashboard aggregate row.
// Reads its filters from the query string (business/type/product_id/
// category_id/start/end) so a dashboard link can land here pre-filtered
// and "back" (browser back button) returns to exactly where the click
// came from — no separate in-page "back to dashboard" state to keep in
// sync. Any role can view (same data the dashboard already shows in
// aggregate); no PII beyond what the rest of the app already exposes —
// customer identity is never fetched or shown here.
const PAGE_SIZE = 25;

type TxType = "sales" | "purchases" | "repairs";

export default function TransactionsPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);

  const initialParams = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : null;
  const [txType, setTxType] = useState<TxType>((initialParams?.get("type") as TxType) || "sales");
  const [productId] = useState(initialParams?.get("product_id") ?? "");
  const [categoryId] = useState(initialParams?.get("category_id") ?? "");
  const [startDate, setStartDate] = useState(initialParams?.get("start") ?? "");
  const [endDate, setEndDate] = useState(initialParams?.get("end") ?? "");
  const [offset, setOffset] = useState(0);

  const [sales, setSales] = useState<PaginatedResult<SaleTransaction> | null>(null);
  const [purchases, setPurchases] = useState<PaginatedResult<PurchaseTransaction> | null>(null);
  const [repairs, setRepairs] = useState<PaginatedResult<RepairTransaction> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function query(): string {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    if (productId && txType !== "repairs") params.set("product_id", productId);
    if (categoryId && txType !== "repairs") params.set("category_id", categoryId);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    return `?${params.toString()}`;
  }

  useEffect(() => {
    if (!businessId) return;
    setLoading(true);
    setError(null);
    const path = `/businesses/${businessId}/transactions/${txType}${query()}`;
    apiGet(path)
      .then((data) => {
        if (txType === "sales") setSales(data as PaginatedResult<SaleTransaction>);
        else if (txType === "purchases") setPurchases(data as PaginatedResult<PurchaseTransaction>);
        else setRepairs(data as PaginatedResult<RepairTransaction>);
      })
      .catch(() => setError("Could not load transactions."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [businessId, txType, startDate, endDate, offset]);

  function switchType(next: TxType) {
    setTxType(next);
    setOffset(0);
  }

  const current = txType === "sales" ? sales : txType === "purchases" ? purchases : repairs;

  if (checkingSession) return <p>Loading…</p>;

  return (
    <main>
      <AppNav businessId={businessId} />
      <h1>Transactions</h1>

      <label htmlFor="business-select">Shop</label>
      <br />
      <select id="business-select" value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
        {businesses.map((b) => (
          <option key={b.id} value={b.id}>
            {businessDisplayLabel(b)}
          </option>
        ))}
      </select>

      <p>
        <button type="button" onClick={() => switchType("sales")} disabled={txType === "sales"}>
          Sales
        </button>{" "}
        <button type="button" onClick={() => switchType("purchases")} disabled={txType === "purchases"}>
          Purchases
        </button>{" "}
        <button type="button" onClick={() => switchType("repairs")} disabled={txType === "repairs"}>
          Repairs
        </button>
      </p>

      {(productId || categoryId) && txType !== "repairs" && (
        <p className="hint">Filtered from a dashboard drill-down — reload this page directly to clear the filter.</p>
      )}

      <label htmlFor="start-date">From</label>{" "}
      <input
        id="start-date"
        type="date"
        value={startDate}
        onChange={(e) => {
          setStartDate(e.target.value);
          setOffset(0);
        }}
      />{" "}
      <label htmlFor="end-date">To</label>{" "}
      <input
        id="end-date"
        type="date"
        value={endDate}
        onChange={(e) => {
          setEndDate(e.target.value);
          setOffset(0);
        }}
      />

      {error && <p className="status-error">{error}</p>}
      {loading && <p>Loading…</p>}

      {!loading && current && current.items.length === 0 && <p>No transactions match this filter.</p>}

      {!loading && txType === "sales" && sales && sales.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Product</th>
              <th>Qty</th>
              <th>Unit price</th>
              <th>Total</th>
              <th>Order ref</th>
            </tr>
          </thead>
          <tbody>
            {sales.items.map((row) => (
              <tr key={row.id}>
                <td>{new Date(row.sold_at).toLocaleDateString()}</td>
                <td>
                  {row.product_name ?? "Unmatched product"}
                  {row.category_name && <span className="hint"> ({row.category_name})</span>}
                </td>
                <td>{row.quantity}</td>
                <td>{formatMoney(row.unit_price)}</td>
                <td>{formatMoney(row.line_total)}</td>
                <td>{row.order_reference ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && txType === "purchases" && purchases && purchases.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Product</th>
              <th>Qty</th>
              <th>Unit cost</th>
              <th>Supplier</th>
              <th>PO/reference</th>
            </tr>
          </thead>
          <tbody>
            {purchases.items.map((row) => (
              <tr key={row.id}>
                <td>{row.event_date ?? "—"}</td>
                <td>
                  {row.product_name ?? "Unmatched product"}
                  {row.category_name && <span className="hint"> ({row.category_name})</span>}
                </td>
                <td>{row.quantity_delta}</td>
                <td>{row.unit_cost !== null ? formatMoney(row.unit_cost) : "—"}</td>
                <td>{row.supplier_name ?? "Unknown"}</td>
                <td>{row.purchase_reference ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && txType === "repairs" && repairs && repairs.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Completed</th>
              <th>Description</th>
              <th>Price charged</th>
              <th>Labour cost</th>
              <th>Job/reference</th>
            </tr>
          </thead>
          <tbody>
            {repairs.items.map((row) => (
              <tr key={row.id}>
                <td>{row.completed_at ? new Date(row.completed_at).toLocaleDateString() : "—"}</td>
                <td>{row.description ?? "—"}</td>
                <td>{row.price_charged !== null ? formatMoney(row.price_charged) : "—"}</td>
                <td>{row.labour_cost !== null ? formatMoney(row.labour_cost) : "—"}</td>
                <td>{row.repair_reference ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {current && current.total > PAGE_SIZE && (
        <p>
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </button>{" "}
          Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, current.total)} of {current.total}{" "}
          <button type="button" disabled={offset + PAGE_SIZE >= current.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
          </button>
        </p>
      )}
    </main>
  );
}
