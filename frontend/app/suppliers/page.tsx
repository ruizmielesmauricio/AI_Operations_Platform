"use client";

import { useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api/client";
import { businessDisplayLabel } from "@/lib/businessLabel";
import { formatMoney } from "@/lib/format";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { Supplier, SupplierAnalytics, SupplierCreateResponse } from "@/types";

// Gap 4 — supplier list/create/edit/merge/deactivate + a basic spend
// analytics table. Owner/manager can write, any role can view (mirrors
// the employee-seats/suppliers backend role split); merge specifically
// is owner-only per direct requirement, enforced again here so the
// button doesn't even appear for a manager (the backend still enforces
// it regardless — this is UX, not the real security boundary).
export default function SuppliersPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);
  const business = businesses.find((b) => b.id === businessId);
  const canWrite = business?.role === "owner" || business?.role === "manager";
  const canMerge = business?.role === "owner";

  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [analytics, setAnalytics] = useState<SupplierAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmingDeactivate, setConfirmingDeactivate] = useState<Supplier | null>(null);

  const [newName, setNewName] = useState("");
  const [newContact, setNewContact] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editContact, setEditContact] = useState("");
  const [mergingId, setMergingId] = useState<string | null>(null);
  const [mergeTargetId, setMergeTargetId] = useState("");

  function load(id: string) {
    setLoading(true);
    setError(null);
    Promise.all([
      apiGet<Supplier[]>(`/businesses/${id}/suppliers`),
      apiGet<SupplierAnalytics>(`/businesses/${id}/suppliers/analytics`),
    ])
      .then(([s, a]) => {
        setSuppliers(s);
        setAnalytics(a);
      })
      .catch(() => setError("Could not load suppliers."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (businessId) load(businessId);
  }, [businessId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      const result = await apiPost<SupplierCreateResponse>(`/businesses/${businessId}/suppliers`, {
        name: newName,
        contact_info: newContact || null,
      });
      setNotice(
        result.created
          ? `Added "${result.supplier.name}".`
          : `"${result.supplier.name}" already exists — matched it instead of creating a duplicate.`
      );
      setNewName("");
      setNewContact("");
      load(businessId);
    } catch {
      setError("Could not add supplier.");
    }
  }

  function startEdit(s: Supplier) {
    setEditingId(s.id);
    setEditName(s.name);
    setEditContact(s.contact_info ?? "");
  }

  async function handleSaveEdit(id: string) {
    setError(null);
    try {
      await apiPatch(`/businesses/${businessId}/suppliers/${id}`, {
        name: editName,
        contact_info: editContact || null,
      });
      setEditingId(null);
      load(businessId);
    } catch {
      setError("Could not save changes.");
    }
  }

  async function handleDeactivate(id: string) {
    setError(null);
    try {
      await apiDelete(`/businesses/${businessId}/suppliers/${id}`);
      load(businessId);
    } catch {
      setError("Could not deactivate supplier.");
    } finally {
      setConfirmingDeactivate(null);
    }
  }

  async function handleMerge(sourceId: string) {
    if (!mergeTargetId) return;
    setError(null);
    try {
      await apiPost(`/businesses/${businessId}/suppliers/${sourceId}/merge`, {
        target_supplier_id: mergeTargetId,
      });
      setNotice("Suppliers merged.");
      setMergingId(null);
      setMergeTargetId("");
      load(businessId);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 400
          ? "A supplier cannot be merged into itself."
          : "Could not merge suppliers."
      );
    }
  }

  if (checkingSession) return <p>Loading…</p>;

  return (
    <main>
      <AppNav businessId={businessId} />
      <ConfirmDialog
        open={confirmingDeactivate !== null}
        title={`Deactivate ${confirmingDeactivate?.name ?? "this supplier"}?`}
        description="This supplier will no longer be available for new purchase matching. Existing purchase history and supplier analytics are retained."
        confirmLabel="Deactivate supplier"
        tone="warning"
        onCancel={() => setConfirmingDeactivate(null)}
        onConfirm={() => confirmingDeactivate && handleDeactivate(confirmingDeactivate.id)}
      />
      <h1>Suppliers</h1>
      <p className="hint">
        Track where your stock comes from. This powers the spend breakdown below, and — once you record a
        supplier&apos;s typical lead time — sharpens the{" "}
        <a href={`/products${businessId ? `?business=${businessId}` : ""}`}>low-stock threshold recommendations</a>.
        Unknown supplier is fine; purchases without one just show up as &quot;Unknown&quot; and you can correct or
        merge suppliers here at any time.
      </p>

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

      {!loading && businessId && (
        <>
          {canWrite && (
            <>
              <h2>Add a supplier</h2>
              <form onSubmit={handleCreate}>
                <label htmlFor="new-supplier-name">Name</label>
                <br />
                <input
                  id="new-supplier-name"
                  required
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <br />
                <label htmlFor="new-supplier-contact">Contact info (optional)</label>
                <br />
                <input
                  id="new-supplier-contact"
                  value={newContact}
                  onChange={(e) => setNewContact(e.target.value)}
                />
                <br />
                <button type="submit">Add supplier</button>
              </form>
            </>
          )}

          <h2>Suppliers</h2>
          {suppliers.length === 0 ? (
            <p>
              No suppliers yet — map a Supplier column on your next purchases upload, or add one manually above.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Contact</th>
                  {canWrite && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {suppliers.map((s) => (
                  <tr key={s.id}>
                    {editingId === s.id ? (
                      <>
                        <td>
                          <input value={editName} onChange={(e) => setEditName(e.target.value)} />
                        </td>
                        <td>
                          <input value={editContact} onChange={(e) => setEditContact(e.target.value)} />
                        </td>
                        <td>
                          <button type="button" onClick={() => handleSaveEdit(s.id)}>
                            Save
                          </button>{" "}
                          <button type="button" onClick={() => setEditingId(null)}>
                            Cancel
                          </button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>{s.name}</td>
                        <td>{s.contact_info ?? "—"}</td>
                        {canWrite && (
                          <td>
                            <button type="button" onClick={() => startEdit(s)}>
                              Edit
                            </button>{" "}
                            <button type="button" onClick={() => setConfirmingDeactivate(s)}>
                              Deactivate
                            </button>{" "}
                            {canMerge &&
                              (mergingId === s.id ? (
                                <>
                                  <select value={mergeTargetId} onChange={(e) => setMergeTargetId(e.target.value)}>
                                    <option value="">Merge into…</option>
                                    {suppliers
                                      .filter((other) => other.id !== s.id)
                                      .map((other) => (
                                        <option key={other.id} value={other.id}>
                                          {other.name}
                                        </option>
                                      ))}
                                  </select>{" "}
                                  <button type="button" onClick={() => handleMerge(s.id)} disabled={!mergeTargetId}>
                                    Confirm merge
                                  </button>{" "}
                                  <button type="button" onClick={() => setMergingId(null)}>
                                    Cancel
                                  </button>
                                </>
                              ) : (
                                <button type="button" onClick={() => setMergingId(s.id)}>
                                  Merge
                                </button>
                              ))}
                          </td>
                        )}
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2>Spend by supplier (last 30 days)</h2>
          {analytics && analytics.rows.length === 0 ? (
            <p>No purchases with a known cost in this period yet.</p>
          ) : (
            analytics && (
              <>
                {analytics.unknown_supplier_share_pct !== null && Number(analytics.unknown_supplier_share_pct) > 0 && (
                  <p className="hint">
                    {analytics.unknown_supplier_share_pct}% of spend has no supplier recorded — map a Supplier
                    column on future purchases uploads to close this gap.
                  </p>
                )}
                <table>
                  <thead>
                    <tr>
                      <th>Supplier</th>
                      <th>Spend</th>
                      <th>Products</th>
                      <th>Purchases</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics.rows.map((row) => (
                      <tr key={row.supplier_id ?? "unknown"}>
                        <td>{row.supplier_name}</td>
                        <td>{formatMoney(row.spend)}</td>
                        <td>{row.product_count}</td>
                        <td>{row.purchase_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )
          )}
        </>
      )}
    </main>
  );
}
