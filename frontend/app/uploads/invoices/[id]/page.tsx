"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { ApiError, apiDelete, apiGet, apiGetBlob, apiPatch, apiPost } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type {
  GlobalSearchResult,
  InvoiceConfirmPreview,
  InvoiceConfirmResponse,
  InvoiceDraft,
  InvoiceDraftLine,
  ProductSearchResult,
  Supplier,
} from "@/types";

// PDF Supplier-Invoice Ingestion — the review/correct/confirm screen.
// This is NOT a blind OCR-to-database feature: nothing here writes to
// stock, supplier spend, costs, or reports until the user explicitly
// reviews and clicks Confirm (backend/app/invoices/service.py::
// confirm_invoice_import).

const ISSUE_LABELS: Record<string, string> = {
  missing_description: "No description found — please fill it in",
  missing_quantity: "No quantity found — please fill it in",
  missing_price: "No unit price or line total found",
  negative_quantity: "Quantity is negative",
  negative_price: "Price is negative",
  quantity_not_whole: "Quantity isn't a whole number — stock is tracked in whole units",
  line_items_not_detected: "We couldn't find a line-item table in this PDF",
  line_total_sum_mismatch_subtotal: "Line totals don't add up to the subtotal",
  grand_total_mismatch: "Subtotal + tax − discount + shipping doesn't match the grand total",
  duplicate_line_detected: "Two lines look identical — check this isn't a duplicate",
  label_found_no_value: "Found a label but no value next to it",
  unparseable: "Found a value we couldn't read",
  low_confidence_fallback: "Guessed — please double-check this",
  no_supplier_signal: "Couldn't find a supplier name in the document",
  no_currency_signal: "Couldn't detect a currency",
  not_found: "Not found in the document",
};

function issueText(code: string): string {
  return ISSUE_LABELS[code] ?? code;
}

const STATUS_LABELS: Record<string, string> = {
  processing: "Processing…",
  needs_review: "Needs review",
  failed: "Could not be read",
  confirmed: "Confirmed",
  reversed: "Undone",
};

const FAILURE_REASON_TEXT: Record<string, string> = {
  encrypted: "This PDF is password-protected. Remove the password and re-upload it.",
  corrupt: "This file couldn't be read as a PDF — it may be damaged or incomplete.",
  oversized: "This PDF has too many pages to process.",
  unsupported_file_type: "This file isn't a real PDF.",
  no_extractable_text: "This looks like a scanned or image-only PDF — we can't read text from it yet. Try a text-based PDF, or use a CSV/XLSX export instead.",
};

function ProductPicker({
  businessId,
  onSelect,
}: {
  businessId: string;
  onSelect: (product: ProductSearchResult) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ProductSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  async function runSearch() {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const result = await apiGet<GlobalSearchResult>(
        `/businesses/${businessId}/search?q=${encodeURIComponent(query.trim())}`
      );
      setResults(result.products);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="invoice-line__product-picker">
      <input
        type="text"
        placeholder="Search products by name or SKU…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            runSearch();
          }
        }}
      />
      <button type="button" onClick={runSearch} disabled={searching || !query.trim()}>
        {searching ? "Searching…" : "Search"}
      </button>
      {results.length > 0 && (
        <ul>
          {results.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => onSelect(p)}>
                {p.name}
                {p.sku ? ` (${p.sku})` : ""}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function InvoiceReviewPage() {
  const { session, checkingSession } = useRequireSession();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const businessId = searchParams.get("business") ?? "";

  const [draft, setDraft] = useState<InvoiceDraft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  const [headerForm, setHeaderForm] = useState<Record<string, string>>({});
  const [savingHeader, setSavingHeader] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [savingLineId, setSavingLineId] = useState<string | null>(null);
  const [pickingProductForLine, setPickingProductForLine] = useState<string | null>(null);

  const [preview, setPreview] = useState<InvoiceConfirmPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [overrideDuplicate, setOverrideDuplicate] = useState(false);
  const [confirmResult, setConfirmResult] = useState<InvoiceConfirmResponse | null>(null);

  const [undoing, setUndoing] = useState(false);
  const [confirmUndoOpen, setConfirmUndoOpen] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [confirmDiscardOpen, setConfirmDiscardOpen] = useState(false);
  const [discarded, setDiscarded] = useState(false);

  const loadDraft = useCallback(() => {
    if (!businessId || !params.id) return;
    apiGet<InvoiceDraft>(`/businesses/${businessId}/invoices/${params.id}`)
      .then((d) => {
        setDraft(d);
        setHeaderForm({
          invoice_reference: d.invoice_reference ?? "",
          invoice_date: d.invoice_date ?? "",
          due_date: d.due_date ?? "",
          currency: d.currency ?? "",
          subtotal: d.subtotal ?? "",
          tax_total: d.tax_total ?? "",
          discount_total: d.discount_total ?? "",
          shipping_total: d.shipping_total ?? "",
          grand_total: d.grand_total ?? "",
          supplier_id: d.supplier_id ?? "",
          supplier_name_input: d.supplier_name_input ?? "",
        });
      })
      .catch(() => setLoadError("Could not load this invoice."));
  }, [businessId, params.id]);

  useEffect(() => {
    loadDraft();
  }, [loadDraft]);

  useEffect(() => {
    if (!businessId) return;
    apiGet<Supplier[]>(`/businesses/${businessId}/suppliers`)
      .then(setSuppliers)
      .catch(() => undefined);
  }, [businessId]);

  // Blob preview — the route requires the same Authorization header
  // every other tenant-scoped route does (unlike the public company-logo
  // route), so a plain <iframe src> can't be used directly.
  useEffect(() => {
    if (!businessId || !params.id || !draft) return;
    if (!["processing", "needs_review", "failed"].includes(draft.status)) {
      setPdfUrl(null);
      return;
    }
    let cancelled = false;
    apiGetBlob(`/businesses/${businessId}/invoices/${params.id}/pdf`)
      .then(({ blob }) => {
        if (!cancelled) setPdfUrl(URL.createObjectURL(blob));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [businessId, params.id, draft?.status]);

  const loadPreview = useCallback(() => {
    if (!businessId || !params.id) return;
    setPreviewLoading(true);
    apiPost<InvoiceConfirmPreview>(`/businesses/${businessId}/invoices/${params.id}/confirm/preview`, {})
      .then(setPreview)
      .catch(() => undefined)
      .finally(() => setPreviewLoading(false));
  }, [businessId, params.id]);

  useEffect(() => {
    if (draft?.status === "needs_review") loadPreview();
  }, [draft?.status, draft?.lines.length, loadPreview]);

  async function saveHeader(e: React.FormEvent) {
    e.preventDefault();
    if (!businessId || !params.id) return;
    setSavingHeader(true);
    setActionError(null);
    try {
      const payload: Record<string, unknown> = {
        invoice_reference: headerForm.invoice_reference || null,
        invoice_date: headerForm.invoice_date || null,
        due_date: headerForm.due_date || null,
        currency: headerForm.currency || null,
        subtotal: headerForm.subtotal || null,
        tax_total: headerForm.tax_total || null,
        discount_total: headerForm.discount_total || null,
        shipping_total: headerForm.shipping_total || null,
        grand_total: headerForm.grand_total || null,
      };
      if (headerForm.supplier_id) {
        payload.supplier_id = headerForm.supplier_id;
        payload.supplier_name_input = null;
      } else {
        payload.supplier_id = null;
        payload.supplier_name_input = headerForm.supplier_name_input || null;
      }
      const updated = await apiPatch<InvoiceDraft>(`/businesses/${businessId}/invoices/${params.id}`, payload);
      setDraft(updated);
      loadPreview();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not save these changes.");
    } finally {
      setSavingHeader(false);
    }
  }

  async function saveLine(lineId: string, fields: Record<string, unknown>) {
    if (!businessId || !params.id) return;
    setSavingLineId(lineId);
    setActionError(null);
    try {
      const updatedLine = await apiPatch<InvoiceDraftLine>(
        `/businesses/${businessId}/invoices/${params.id}/lines/${lineId}`,
        fields
      );
      setDraft((prev) => (prev ? { ...prev, lines: prev.lines.map((l) => (l.id === lineId ? updatedLine : l)) } : prev));
      loadPreview();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not save this line.");
    } finally {
      setSavingLineId(null);
    }
  }

  async function handleConfirm() {
    if (!businessId || !params.id) return;
    setConfirming(true);
    setActionError(null);
    try {
      const result = await apiPost<InvoiceConfirmResponse>(`/businesses/${businessId}/invoices/${params.id}/confirm`, {
        override_duplicate_warning: overrideDuplicate,
      });
      setConfirmResult(result);
      setConfirmDialogOpen(false);
      loadDraft();
    } catch (err) {
      // ApiError.message already carries the backend's plain-string
      // detail (e.g. "This invoice has already been imported" for a 409)
      // — same convention as every other route in this app.
      setActionError(err instanceof ApiError ? err.message : "Could not confirm this import.");
      setConfirmDialogOpen(false);
    } finally {
      setConfirming(false);
    }
  }

  async function handleUndo() {
    if (!businessId || !params.id) return;
    setUndoing(true);
    setActionError(null);
    try {
      await apiPost(`/businesses/${businessId}/invoices/${params.id}/undo`, {});
      setConfirmUndoOpen(false);
      loadDraft();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not undo this import.");
      setConfirmUndoOpen(false);
    } finally {
      setUndoing(false);
    }
  }

  async function handleDiscard() {
    if (!businessId || !params.id) return;
    setDiscarding(true);
    setActionError(null);
    try {
      await apiDelete(`/businesses/${businessId}/invoices/${params.id}`);
      setConfirmDiscardOpen(false);
      setDiscarded(true);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not discard this draft.");
      setConfirmDiscardOpen(false);
    } finally {
      setDiscarding(false);
    }
  }

  if (checkingSession) {
    return (
      <main>
        <p>Checking session…</p>
      </main>
    );
  }

  if (!session) {
    return (
      <main>
        <p>Supabase is not configured yet — set NEXT_PUBLIC_SUPABASE_URL/ANON_KEY in frontend/.env.local.</p>
      </main>
    );
  }

  if (!businessId) {
    return (
      <main>
        <h1>Invoice</h1>
        <p>
          No business selected — go back to <a href="/uploads">Upload data</a>.
        </p>
      </main>
    );
  }

  if (discarded) {
    return (
      <main>
        <AppNav businessId={businessId} />
        <h1>Invoice discarded</h1>
        <p>
          Nothing was imported. <a href={`/uploads?business=${businessId}`}>Back to Upload data</a>.
        </p>
      </main>
    );
  }

  if (loadError) {
    return (
      <main>
        <AppNav businessId={businessId} />
        <p className="status-error">{loadError}</p>
      </main>
    );
  }

  if (!draft) {
    return (
      <main>
        <AppNav businessId={businessId} />
        <p>Loading…</p>
      </main>
    );
  }

  const blockingLines = draft.lines.filter(
    (l) =>
      l.resolution_action !== "excluded" &&
      (l.resolution_action === "unresolved" ||
        (l.resolution_action === "match_existing" && !l.matched_product_id) ||
        (l.resolution_action === "create_new" && !l.proposed_name && !l.proposed_sku))
  );

  return (
    <main>
      <AppNav businessId={businessId} />
      <ConfirmDialog
        open={confirmDialogOpen}
        title="Confirm this import?"
        description={
          preview
            ? `This will match ${preview.products_to_match} existing product(s), create ${preview.products_to_create} new product(s), ` +
              `record ${preview.purchase_movement_count} purchase movement(s)` +
              (preview.lines_excluded > 0 ? `, and skip ${preview.lines_excluded} excluded line(s)` : "") +
              `. Supplier: ${preview.supplier_action === "unknown" ? "Unknown" : preview.supplier_name ?? "Unknown"}` +
              (preview.supplier_action === "create_new" ? " (new)" : "") +
              "."
            : "This will import the reviewed lines into your purchase records."
        }
        confirmLabel="Confirm import"
        tone="warning"
        busy={confirming}
        onCancel={() => setConfirmDialogOpen(false)}
        onConfirm={handleConfirm}
      />
      <ConfirmDialog
        open={confirmUndoOpen}
        title="Undo this import?"
        description="This reverses the purchase records and stock changes this invoice created. Products or suppliers it created are kept."
        confirmLabel="Undo import"
        tone="danger"
        busy={undoing}
        onCancel={() => setConfirmUndoOpen(false)}
        onConfirm={handleUndo}
      />
      <ConfirmDialog
        open={confirmDiscardOpen}
        title="Discard this invoice?"
        description="The uploaded file and everything extracted from it will be deleted. Nothing has been imported yet."
        confirmLabel="Discard"
        tone="danger"
        busy={discarding}
        onCancel={() => setConfirmDiscardOpen(false)}
        onConfirm={handleDiscard}
      />

      <h1>Invoice: {draft.original_filename}</h1>
      <p>
        Status: <strong>{STATUS_LABELS[draft.status] ?? draft.status}</strong>
      </p>

      {draft.status === "failed" && draft.failure_reason && (
        <p className="status-error">
          {FAILURE_REASON_TEXT[draft.failure_reason] ?? "This invoice couldn't be processed."}
        </p>
      )}

      {draft.status === "confirmed" && (
        <p className="status-ok">
          Imported successfully. <a href={`/transactions?business=${businessId}&tab=purchases`}>View in Transactions</a>.
        </p>
      )}
      {confirmResult && (
        <p className="status-ok">
          {confirmResult.rows_imported} line(s) imported
          {confirmResult.rows_rejected > 0 ? `, ${confirmResult.rows_rejected} rejected as duplicates` : ""}.
        </p>
      )}

      {draft.status === "reversed" && <p className="status-warn">This import was undone.</p>}

      {actionError && <p className="status-error">{actionError}</p>}

      {pdfUrl && (
        <details open>
          <summary>Original PDF</summary>
          <iframe src={pdfUrl} title="Original invoice PDF" style={{ width: "100%", height: 480, border: "1px solid #ccc" }} />
        </details>
      )}

      {(draft.status === "needs_review" || draft.status === "confirmed" || draft.status === "reversed") && (
        <>
          {draft.duplicate_status === "exact" && (
            <p className="status-error">
              This looks like an exact duplicate of an invoice already imported. It can&apos;t be confirmed again.
            </p>
          )}
          {draft.duplicate_status === "plausible" && draft.status === "needs_review" && (
            <div className="status-warn">
              <p>This looks like it might be a duplicate of an already-imported invoice (same date, currency, and total).</p>
              <label>
                <input
                  type="checkbox"
                  checked={overrideDuplicate}
                  onChange={(e) => setOverrideDuplicate(e.target.checked)}
                />{" "}
                I&apos;ve checked — this is a genuinely different invoice, import it anyway
              </label>
            </div>
          )}

          <h2>Invoice details</h2>
          <form onSubmit={saveHeader}>
            <div>
              <label htmlFor="supplier-select">Supplier</label>
              <br />
              <select
                id="supplier-select"
                disabled={draft.status !== "needs_review"}
                value={headerForm.supplier_id ?? ""}
                onChange={(e) => setHeaderForm((prev) => ({ ...prev, supplier_id: e.target.value }))}
              >
                <option value="">— Unknown / new supplier —</option>
                {suppliers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              {!headerForm.supplier_id && (
                <>
                  <br />
                  <input
                    type="text"
                    placeholder="New supplier name (leave blank for Unknown supplier)"
                    disabled={draft.status !== "needs_review"}
                    value={headerForm.supplier_name_input ?? ""}
                    onChange={(e) => setHeaderForm((prev) => ({ ...prev, supplier_name_input: e.target.value }))}
                  />
                </>
              )}
              {draft.matched_supplier_name && headerForm.supplier_id && (
                <span className="hint"> — matched to existing supplier &quot;{draft.matched_supplier_name}&quot;</span>
              )}
            </div>

            <div>
              <label htmlFor="invoice-reference">Invoice reference</label>
              <br />
              <input
                id="invoice-reference"
                type="text"
                disabled={draft.status !== "needs_review"}
                value={headerForm.invoice_reference ?? ""}
                onChange={(e) => setHeaderForm((prev) => ({ ...prev, invoice_reference: e.target.value }))}
              />
            </div>
            <div>
              <label htmlFor="invoice-date">Invoice date</label>
              <br />
              <input
                id="invoice-date"
                type="date"
                disabled={draft.status !== "needs_review"}
                value={headerForm.invoice_date ?? ""}
                onChange={(e) => setHeaderForm((prev) => ({ ...prev, invoice_date: e.target.value }))}
              />
              {!draft.invoice_date && draft.status === "needs_review" && (
                <span className="status-error"> — required before this can be confirmed</span>
              )}
            </div>
            <div>
              <label htmlFor="due-date">Due date</label>
              <br />
              <input
                id="due-date"
                type="date"
                disabled={draft.status !== "needs_review"}
                value={headerForm.due_date ?? ""}
                onChange={(e) => setHeaderForm((prev) => ({ ...prev, due_date: e.target.value }))}
              />
            </div>
            <div>
              <label htmlFor="currency">Currency</label>
              <br />
              <input
                id="currency"
                type="text"
                disabled={draft.status !== "needs_review"}
                value={headerForm.currency ?? ""}
                onChange={(e) => setHeaderForm((prev) => ({ ...prev, currency: e.target.value }))}
              />
            </div>
            {(["subtotal", "tax_total", "discount_total", "shipping_total", "grand_total"] as const).map((field) => (
              <div key={field}>
                <label htmlFor={field}>{field.replace("_", " ")}</label>
                <br />
                <input
                  id={field}
                  type="text"
                  inputMode="decimal"
                  disabled={draft.status !== "needs_review"}
                  value={headerForm[field] ?? ""}
                  onChange={(e) => setHeaderForm((prev) => ({ ...prev, [field]: e.target.value }))}
                />
              </div>
            ))}
            {draft.header_issue_codes && draft.header_issue_codes.length > 0 && (
              <ul>
                {draft.header_issue_codes.map((code) => (
                  <li key={code} className="status-warn">
                    {issueText(code)}
                  </li>
                ))}
              </ul>
            )}
            {draft.status === "needs_review" && (
              <button type="submit" disabled={savingHeader}>
                {savingHeader ? "Saving…" : "Save changes"}
              </button>
            )}
          </form>

          <h2>Line items</h2>
          {draft.lines.length === 0 ? (
            <p className="status-warn">
              We couldn&apos;t find a line-item table in this PDF. This invoice can&apos;t be imported through this
              screen yet — try a CSV/XLSX export, or contact support.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Description</th>
                  <th>Supplier SKU</th>
                  <th>Qty</th>
                  <th>Unit price</th>
                  <th>Line total</th>
                  <th>Match</th>
                  <th>Issue</th>
                </tr>
              </thead>
              <tbody>
                {draft.lines.map((line) => {
                  const editable = draft.status === "needs_review";
                  const saving = savingLineId === line.id;
                  return (
                    <tr key={line.id}>
                      <td>
                        <input
                          type="text"
                          disabled={!editable}
                          defaultValue={line.description ?? ""}
                          onBlur={(e) => {
                            if (e.target.value !== (line.description ?? "")) {
                              saveLine(line.id, { description: e.target.value || null });
                            }
                          }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          disabled={!editable}
                          defaultValue={line.supplier_sku ?? ""}
                          onBlur={(e) => {
                            if (e.target.value !== (line.supplier_sku ?? "")) {
                              saveLine(line.id, { supplier_sku: e.target.value || null });
                            }
                          }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          disabled={!editable}
                          defaultValue={line.quantity ?? ""}
                          onBlur={(e) => {
                            if (e.target.value !== (line.quantity ?? "")) {
                              saveLine(line.id, { quantity: e.target.value || null });
                            }
                          }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          disabled={!editable}
                          defaultValue={line.unit_price ?? ""}
                          onBlur={(e) => {
                            if (e.target.value !== (line.unit_price ?? "")) {
                              saveLine(line.id, { unit_price: e.target.value || null });
                            }
                          }}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          inputMode="decimal"
                          disabled={!editable}
                          defaultValue={line.line_total ?? ""}
                          onBlur={(e) => {
                            if (e.target.value !== (line.line_total ?? "")) {
                              saveLine(line.id, { line_total: e.target.value || null });
                            }
                          }}
                        />
                      </td>
                      <td>
                        <select
                          disabled={!editable || saving}
                          value={line.resolution_action}
                          onChange={(e) => saveLine(line.id, { resolution_action: e.target.value })}
                        >
                          <option value="unresolved">Not resolved yet</option>
                          <option value="match_existing">Match existing product</option>
                          <option value="create_new">Create new product</option>
                          <option value="excluded">Exclude this line</option>
                        </select>
                        {line.resolution_action === "match_existing" && (
                          <div>
                            {line.matched_product_id ? (
                              <span>
                                Matched: {line.matched_product_name ?? "(unknown)"}
                                {line.matched_product_sku ? ` (${line.matched_product_sku})` : ""}
                              </span>
                            ) : (
                              <span className="status-warn">No product selected</span>
                            )}
                            {editable && (
                              <>
                                {" "}
                                <button
                                  type="button"
                                  onClick={() => setPickingProductForLine(pickingProductForLine === line.id ? null : line.id)}
                                >
                                  {pickingProductForLine === line.id ? "Cancel" : "Choose product"}
                                </button>
                                {pickingProductForLine === line.id && (
                                  <ProductPicker
                                    businessId={businessId}
                                    onSelect={(product) => {
                                      saveLine(line.id, { matched_product_id: product.id });
                                      setPickingProductForLine(null);
                                    }}
                                  />
                                )}
                              </>
                            )}
                          </div>
                        )}
                        {line.resolution_action === "create_new" && (
                          <div>
                            <input
                              type="text"
                              placeholder="New product name"
                              disabled={!editable}
                              defaultValue={line.proposed_name ?? ""}
                              onBlur={(e) => {
                                if (e.target.value !== (line.proposed_name ?? "")) {
                                  saveLine(line.id, { proposed_name: e.target.value || null });
                                }
                              }}
                            />
                            <input
                              type="text"
                              placeholder="New SKU (optional)"
                              disabled={!editable}
                              defaultValue={line.proposed_sku ?? ""}
                              onBlur={(e) => {
                                if (e.target.value !== (line.proposed_sku ?? "")) {
                                  saveLine(line.id, { proposed_sku: e.target.value || null });
                                }
                              }}
                            />
                          </div>
                        )}
                      </td>
                      <td>{line.issue_code && <span className="status-warn">{issueText(line.issue_code)}</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {draft.status === "needs_review" && (
            <>
              <h2>Confirm import</h2>
              {previewLoading && <p>Checking what will happen…</p>}
              {preview && (
                <ul>
                  <li>{preview.products_to_match} product(s) matched to existing products</li>
                  <li>{preview.products_to_create} new product(s) will be created</li>
                  {preview.lines_excluded > 0 && <li>{preview.lines_excluded} line(s) excluded</li>}
                  <li>
                    Supplier: {preview.supplier_action === "unknown" ? "Unknown" : preview.supplier_name ?? "Unknown"}
                    {preview.supplier_action === "create_new" ? " (new)" : ""}
                  </li>
                  <li>{preview.purchase_movement_count} purchase movement(s) will be recorded</li>
                  {preview.invoice_date && <li>Purchase date: {preview.invoice_date}</li>}
                </ul>
              )}
              {blockingLines.length > 0 && (
                <p className="status-error">
                  {blockingLines.length} line(s) still need a decision (match, create, or exclude) before this can be
                  confirmed.
                </p>
              )}
              {!draft.invoice_date && <p className="status-error">An invoice date is required before this can be confirmed.</p>}
              <button
                type="button"
                disabled={
                  blockingLines.length > 0 ||
                  !draft.invoice_date ||
                  draft.duplicate_status === "exact" ||
                  (draft.duplicate_status === "plausible" && !overrideDuplicate)
                }
                onClick={() => setConfirmDialogOpen(true)}
              >
                Confirm import
              </button>{" "}
              <button type="button" onClick={() => setConfirmDiscardOpen(true)}>
                Discard
              </button>
            </>
          )}

          {draft.status === "confirmed" && (
            <button type="button" onClick={() => setConfirmUndoOpen(true)}>
              Undo import
            </button>
          )}
        </>
      )}

      {draft.status === "failed" && (
        <button type="button" onClick={() => setConfirmDiscardOpen(true)} disabled={discarding}>
          Discard
        </button>
      )}

      <p>
        <a href={`/uploads?business=${businessId}`}>Back to Upload data</a>
      </p>
    </main>
  );
}
