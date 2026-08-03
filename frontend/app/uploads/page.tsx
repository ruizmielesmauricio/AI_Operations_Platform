"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api/client";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type {
  Business,
  ConfirmMappingResponse,
  DetectMappingResponse,
  ImportRunResponse,
  ImportUndoResponse,
  RejectionSummary,
  Upload,
} from "@/types";

// Client-side hint only (the `accept` attribute) — the backend is the
// actual gate on which extensions are allowed (PR-2.1, app/imports/service.py).
const ACCEPTED_EXTENSIONS = ".csv,.xls,.xlsx";

// Only "sales" exists today, but this is a dropdown (not a hidden default)
// so adding a second entity type later is a new option here, not new UI —
// same pattern as onboarding's business-template dropdown.
const ENTITY_TYPES = [{ value: "sales", label: "Sales transactions" }];

// Order matters here: it's the order fields are asked about on the
// confirmation screen (PR-2.4).
const FIELD_ORDER = [
  "sale_date",
  "product_name",
  "sku",
  "quantity",
  "unit_price",
  "total_amount",
  "cost_price_at_sale",
  "order_reference",
];

const FIELD_LABELS: Record<string, string> = {
  sale_date: "Which column is the sale date?",
  product_name: "Which column is the product name?",
  sku: "Which column is the SKU or product code? (optional)",
  quantity: "Which column is the quantity sold?",
  unit_price: "Which column is the unit price?",
  total_amount: "Which column is the total amount? (optional if unit price is set)",
  cost_price_at_sale: "Which column is the cost price? (optional)",
  order_reference: "Which column is the order or receipt number? (optional — groups multiple rows into one sale)",
};

const NOT_PRESENT = "";

export default function UploadsPage() {
  const { session, checkingSession } = useRequireSession();
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [businessId, setBusinessId] = useState<string>("");
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [entityType, setEntityType] = useState(ENTITY_TYPES[0].value);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // The upload currently going through mapping confirmation, if any.
  const [mappingUploadId, setMappingUploadId] = useState<string | null>(null);
  const [detection, setDetection] = useState<DetectMappingResponse | null>(null);
  const [fieldMapping, setFieldMapping] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [mappingError, setMappingError] = useState<string | null>(null);

  // Set when auto-detection can't confidently find the header row —
  // rendered as a "click the header row" picker instead of the normal
  // field-confirmation form. chosenHeaderRowIndex carries the pick through
  // to confirm-mapping once the user gets there.
  const [previewRows, setPreviewRows] = useState<string[][] | null>(null);
  const [chosenHeaderRowIndex, setChosenHeaderRowIndex] = useState<number | null>(null);

  // Per-upload so running/undoing one row's import doesn't disable another's.
  const [runningUploadId, setRunningUploadId] = useState<string | null>(null);
  const [undoingRecordId, setUndoingRecordId] = useState<string | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (session) {
      apiGet<Business[]>("/businesses")
        .then((rows) => {
          setBusinesses(rows);
          const requested = new URLSearchParams(window.location.search).get("business");
          const preselect = rows.find((b) => b.id === requested)?.id;
          setBusinessId((current) => current || preselect || rows[0]?.id || "");
        })
        .catch(() => undefined);
    }
  }, [session]);

  const loadUploads = useCallback((id: string) => {
    apiGet<Upload[]>(`/businesses/${id}/uploads`)
      .then(setUploads)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (businessId) loadUploads(businessId);
  }, [businessId, loadUploads]);

  function sampleValuesFor(column: string): string[] {
    if (!detection) return [];
    for (const candidates of Object.values(detection.field_candidates)) {
      const match = candidates.find((c) => c.source_column === column);
      if (match) return match.sample_values;
    }
    return [];
  }

  // Matches the backend's confidence bands (app/imports/detection.py):
  // >=0.85 is a confident match, shown plainly; anything below that was
  // still pre-filled but is worth a second look before trusting it.
  const HIGH_CONFIDENCE = 0.85;

  function confidenceFor(field: string, column: string): number | null {
    if (!detection || !column) return null;
    const match = detection.field_candidates[field]?.find((c) => c.source_column === column);
    return match ? match.confidence : null;
  }

  async function startMapping(uploadId: string, headerRowIndex?: number) {
    setMappingError(null);
    try {
      const body = headerRowIndex === undefined ? {} : { header_row_index: headerRowIndex };
      const result = await apiPost<DetectMappingResponse>(
        `/businesses/${businessId}/uploads/${uploadId}/detect-mapping`,
        body
      );
      if (result.status === "reused") {
        setNotice("Recognized this file from a previous upload — mapping applied automatically.");
        setMappingUploadId(null);
        setDetection(null);
        setPreviewRows(null);
        loadUploads(businessId);
        return;
      }
      if (result.status === "header_not_found") {
        setMappingUploadId(uploadId);
        setDetection(null);
        setPreviewRows(result.preview_rows);
        return;
      }
      setMappingUploadId(uploadId);
      setPreviewRows(null);
      setChosenHeaderRowIndex(headerRowIndex ?? null);
      setDetection(result);
      setFieldMapping(
        Object.fromEntries(
          FIELD_ORDER.map((field) => [field, result.suggested_mapping[field] ?? NOT_PRESENT])
        )
      );
    } catch {
      setMappingError("Could not read this file's columns. Is the backend running?");
    }
  }

  function handlePickHeaderRow(rowIndex: number) {
    if (mappingUploadId) startMapping(mappingUploadId, rowIndex);
  }

  async function handleConfirmMapping(e: React.FormEvent) {
    e.preventDefault();
    if (!mappingUploadId) return;
    setConfirming(true);
    setMappingError(null);
    try {
      const fieldValues = Object.fromEntries(
        FIELD_ORDER.map((field) => [field, fieldMapping[field] || null])
      );
      await apiPost<ConfirmMappingResponse>(
        `/businesses/${businessId}/uploads/${mappingUploadId}/confirm-mapping`,
        { field_mapping: fieldValues, header_row_index: chosenHeaderRowIndex }
      );
      setNotice("Mapping saved.");
      setMappingUploadId(null);
      setDetection(null);
      setPreviewRows(null);
      setChosenHeaderRowIndex(null);
      loadUploads(businessId);
    } catch {
      setMappingError(
        "Could not save this mapping — make sure a sale date and a price field are mapped."
      );
    } finally {
      setConfirming(false);
    }
  }

  async function handleRunImport(uploadId: string) {
    setRunningUploadId(uploadId);
    setActionErrors((prev) => ({ ...prev, [uploadId]: "" }));
    try {
      await apiPost<ImportRunResponse>(`/businesses/${businessId}/uploads/${uploadId}/import`, {});
      loadUploads(businessId);
    } catch {
      setActionErrors((prev) => ({
        ...prev,
        [uploadId]: "Could not run the import. Try again, or check the file hasn't changed.",
      }));
    } finally {
      setRunningUploadId(null);
    }
  }

  async function handleUndo(importRecordId: string) {
    setUndoingRecordId(importRecordId);
    setActionErrors((prev) => ({ ...prev, [importRecordId]: "" }));
    try {
      await apiPost<ImportUndoResponse>(
        `/businesses/${businessId}/import-records/${importRecordId}/undo`,
        {}
      );
      loadUploads(businessId);
    } catch {
      setActionErrors((prev) => ({ ...prev, [importRecordId]: "Could not undo this import." }));
    } finally {
      setUndoingRecordId(null);
    }
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !businessId) return;
    setError(null);
    setNotice(null);
    setUploading(true);
    try {
      const { id, upload_url } = await apiPost<{ id: string; upload_url: string }>(
        `/businesses/${businessId}/uploads`,
        { filename: file.name, entity_type: entityType }
      );

      // The file goes straight from the browser to R2 — it never transits
      // our backend — so this is a plain fetch, not the authenticated
      // apiPost helper (R2's presigned URL is its own auth).
      const putResponse = await fetch(upload_url, { method: "PUT", body: file });
      if (!putResponse.ok) {
        throw new Error(`Upload to storage failed with ${putResponse.status}`);
      }

      await apiPost(`/businesses/${businessId}/uploads/${id}/complete`, {});
      window.alert("Uploaded successfully.");

      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      loadUploads(businessId);
      await startMapping(id);
    } catch {
      setError("Upload failed. Make sure the file is a CSV, XLS, or XLSX export.");
    } finally {
      setUploading(false);
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

  if (businesses.length === 0) {
    return (
      <main>
        <h1>Upload data</h1>
        <p>
          No business yet — <a href="/onboarding">create one first</a>.
        </p>
      </main>
    );
  }

  return (
    <main>
      <h1>Upload data</h1>

      {businesses.length > 1 && (
        <div>
          <label htmlFor="business">Business</label>
          <br />
          <select id="business" value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {!mappingUploadId && (
        <form onSubmit={handleUpload}>
          <div>
            <label htmlFor="entity-type">What does this file contain?</label>
            <br />
            <select id="entity-type" value={entityType} onChange={(e) => setEntityType(e.target.value)}>
              {ENTITY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="file">Export file (CSV, XLS, or XLSX — any format your system produces)</label>
            <br />
            <input
              id="file"
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          {error && <p className="status-error">{error}</p>}
          {notice && <p className="status-ok">{notice}</p>}
          <button type="submit" disabled={!file || uploading}>
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </form>
      )}

      {mappingUploadId && previewRows && (
        <div>
          <h2>Which row is the header?</h2>
          <p>
            We couldn't tell automatically — click the row that has the column names in it
            (e.g. "Date", "Item", "Price").
          </p>
          <table>
            <tbody>
              {previewRows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  <td>
                    <button type="button" onClick={() => handlePickHeaderRow(rowIndex)}>
                      Use this row
                    </button>
                  </td>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {mappingError && <p className="status-error">{mappingError}</p>}
        </div>
      )}

      {mappingUploadId && detection && (
        <form onSubmit={handleConfirmMapping}>
          <h2>Confirm what each column means</h2>
          <p>We matched most columns automatically — check them, and fix anything that's wrong.</p>
          {FIELD_ORDER.map((field) => {
            const selected = fieldMapping[field] ?? "";
            const samples = sampleValuesFor(selected);
            const confidence = confidenceFor(field, selected);
            const needsDoubleCheck = confidence !== null && confidence < HIGH_CONFIDENCE;
            return (
              <div key={field}>
                <label htmlFor={`field-${field}`}>{FIELD_LABELS[field]}</label>
                <br />
                <select
                  id={`field-${field}`}
                  value={fieldMapping[field] ?? NOT_PRESENT}
                  onChange={(e) => setFieldMapping((prev) => ({ ...prev, [field]: e.target.value }))}
                >
                  <option value={NOT_PRESENT}>Not present in this file</option>
                  {detection.columns.map((col) => (
                    <option key={col} value={col}>
                      {col}
                    </option>
                  ))}
                </select>
                {samples.length > 0 && (
                  <span> — e.g. {samples.join(", ")}</span>
                )}
                {needsDoubleCheck && (
                  <div className="status-warn">Double check this one — we're not fully confident in this match.</div>
                )}
              </div>
            );
          })}
          {detection.unmapped_columns.length > 0 && (
            <p>Not used: {detection.unmapped_columns.join(", ")}</p>
          )}
          {mappingError && <p className="status-error">{mappingError}</p>}
          <button type="submit" disabled={confirming}>
            {confirming ? "Saving…" : "Confirm mapping"}
          </button>
        </form>
      )}

      <h2>Past uploads</h2>
      {uploads.length === 0 ? (
        <p>No uploads yet.</p>
      ) : (
        <ul>
          {uploads.map((u) => {
            const record = u.import_record;
            const isRunning = runningUploadId === u.id;
            const isUndoing = record ? undoingRecordId === record.id : false;
            const rowError = actionErrors[u.id] || (record ? actionErrors[record.id] : "");
            return (
              <li key={u.id}>
                {u.original_filename} —{" "}
                <span className={u.status === "imported" ? "status-ok" : ""}>{u.status}</span>{" "}
                ({new Date(u.created_at).toLocaleString()})
                {u.status === "uploaded" && !mappingUploadId && (
                  <>
                    {" "}
                    <button type="button" onClick={() => startMapping(u.id)}>
                      Map columns
                    </button>
                  </>
                )}
                {u.status === "mapped" && (
                  <>
                    {" "}
                    <button type="button" disabled={isRunning} onClick={() => handleRunImport(u.id)}>
                      {isRunning ? "Running…" : "Run import"}
                    </button>
                  </>
                )}
                {record && record.status === "completed" && (
                  <div>
                    <span className="status-ok">
                      {record.rows_imported} of {record.rows_total} rows imported
                    </span>
                    {record.rows_rejected > 0 && (
                      <span className="status-warn"> — {record.rows_rejected} skipped</span>
                    )}
                    {renderRejectionSummary(record.rejection_summary)}
                    {" "}
                    <button type="button" disabled={isUndoing} onClick={() => handleUndo(record.id)}>
                      {isUndoing ? "Undoing…" : "Undo import"}
                    </button>
                  </div>
                )}
                {record && record.status === "reversed" && (
                  <div className="status-warn">
                    Reversed
                    {record.reversed_at ? ` on ${new Date(record.reversed_at).toLocaleString()}` : ""}
                  </div>
                )}
                {rowError && <div className="status-error">{rowError}</div>}
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}

function renderRejectionSummary(summary: RejectionSummary | null) {
  if (!summary) return null;
  const reasons = Object.values(summary.reasons ?? {});
  const warnings = Object.values(summary.warnings ?? {});
  if (reasons.length === 0 && warnings.length === 0) return null;
  return (
    <ul>
      {reasons.map((r) => (
        <li key={r.message} className="status-warn">
          {r.message}
        </li>
      ))}
      {warnings.map((w) => (
        <li key={w.message}>{w.message}</li>
      ))}
    </ul>
  );
}
