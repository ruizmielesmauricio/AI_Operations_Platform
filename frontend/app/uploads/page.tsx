"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiGet, apiPost } from "@/lib/api/client";
import { businessDisplayLabel } from "@/lib/businessLabel";
import { redirectToCheckout } from "@/lib/billing";
import { AppNav } from "@/components/AppNav";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type {
  ConfirmMappingResponse,
  DetectMappingResponse,
  ImportRunResponse,
  ImportUndoResponse,
  RejectionSummary,
  SubscriptionStatus,
  Upload,
  UploadFreshnessEntry,
} from "@/types";

// Past this many days since the last completed upload, the freshness
// indicator switches to its warning style — matches the "upload weekly"
// cadence a restocking shop is nudged toward. Purely a passive, on-request
// indicator (no push/email notification — no scheduler exists yet to fire
// one; see 11_Development_Roadmap.md Stage D17).
const STALE_AFTER_DAYS = 7;

// Client-side hint only (the `accept` attribute) — the backend is the
// actual gate on which extensions are allowed (PR-2.1, app/imports/service.py).
const ACCEPTED_EXTENSIONS = ".csv,.xls,.xlsx";

const ENTITY_TYPES = [
  { value: "sales", label: "Sales transactions" },
  { value: "inventory", label: "Inventory / stock count" },
  { value: "purchases", label: "Purchases / restocking" },
  { value: "repairs", label: "Repairs" },
];

// Keyed by entity_type — order matters within each: it's the order fields
// are asked about on the confirmation screen (PR-2.4). Must list exactly
// the same fields as backend/app/imports/aliases.py::CANONICAL_FIELDS for
// each entity type — confirm-mapping rejects anything else outright
// (app/imports/service.py::confirm_mapping requires an exact key-set
// match). "category" was missing here entirely (added to CANONICAL_FIELDS
// for sales/inventory/purchases as part of the product-categories feature,
// never mirrored to this list) — every sales/inventory/purchases mapping
// confirmation was silently guaranteed to fail with "must include exactly
// the canonical fields," regardless of how correct the visible mapping
// looked, until this was caught and fixed.
const FIELD_ORDER: Record<string, string[]> = {
  sales: [
    "sale_date",
    "product_name",
    "sku",
    "quantity",
    "unit_price",
    "total_amount",
    "cost_price_at_sale",
    "tax_amount",
    "order_reference",
    "category",
    "location",
  ],
  inventory: ["product_name", "sku", "quantity_on_hand", "unit_cost", "category", "location", "as_of_date"],
  purchases: [
    "purchase_date",
    "product_name",
    "sku",
    "quantity_received",
    "unit_cost",
    "purchase_reference",
    "category",
    "supplier",
    "location",
  ],
  repairs: ["repair_date", "description", "price_charged", "labour_cost", "tax_amount", "repair_reference", "location"],
};

const FIELD_LABELS: Record<string, Record<string, string>> = {
  sales: {
    sale_date: "Which column is the sale date?",
    product_name: "Which column is the product name?",
    sku: "Which column is the SKU or product code? (optional)",
    quantity: "Which column is the quantity sold?",
    unit_price: "Which column is the price per unit? (optional)",
    total_amount: "Which column is the final total for this line? (optional if unit price is set)",
    cost_price_at_sale: "Which column is your cost for this item? (optional)",
    tax_amount: "Which column is the tax/VAT amount? (optional)",
    order_reference: "Which column is the order or receipt number? (optional — groups multiple rows into one sale)",
    category: "Which column is the product category or department? (optional)",
    location: "Which column is the store, branch, or location? (optional)",
  },
  inventory: {
    product_name: "Which column is the product name? (optional if SKU is set)",
    sku: "Which column is the SKU or product code? (optional if product name is set)",
    quantity_on_hand: "Which column is the current quantity in stock?",
    unit_cost: "Which column is the unit cost? (optional — sets or updates this product's recorded cost)",
    category: "Which column is the product category or department? (optional)",
    location: "Which column is the store, branch, or location? (optional)",
    as_of_date: "Which column is the date this count was taken? (optional)",
  },
  purchases: {
    purchase_date: "Which column is the date the stock was received?",
    product_name: "Which column is the product name? (optional if SKU is set)",
    sku: "Which column is the SKU or product code? (optional if product name is set)",
    quantity_received: "Which column is the quantity received?",
    unit_cost: "Which column is the unit cost? (optional — updates this product's recorded cost)",
    purchase_reference: "Which column is the PO or invoice number? (optional)",
    category: "Which column is the product category or department? (optional)",
    supplier: "Which column is the supplier or vendor name? (optional)",
    location: "Which column is the store, branch, or location? (optional)",
  },
  repairs: {
    repair_date: "Which column is the repair date?",
    description: "Which column describes the work performed? (optional if price or labour cost is set)",
    price_charged: "Which column is the price charged to the customer? (optional)",
    labour_cost: "Which column is your labour cost for this job? (optional)",
    tax_amount: "Which column is the tax/VAT amount? (optional)",
    repair_reference: "Which column is the job or invoice number? (optional)",
    location: "Which column is the store, branch, or location? (optional)",
  },
};

// Secondary explanatory text, rendered smaller/muted below the question
// (see the .hint CSS class) — kept separate from FIELD_LABELS above so
// the primary question stays short and scannable. Only fields where the
// short question alone leaves real ambiguity get one.
// Shared across all four entity types — only map this if every row in the
// file is genuinely from one location. If it has more than one value,
// confirm-mapping blocks with a prompt to add a branch instead
// (app/imports/service.py::confirm_mapping, BD-007).
const LOCATION_HINT =
  "Only map this if your export includes it. If this column has more than one value, we'll ask you to " +
  "confirm this file is really all one location before importing — each additional location is billed " +
  "separately as its own branch.";

const FIELD_HINTS: Record<string, Record<string, string>> = {
  sales: {
    unit_price: "What the customer paid for one item — before tax, if your file has a separate tax column.",
    total_amount:
      "The actual amount charged for this line — e.g. €36.90 for 3 items at €10 plus €6.90 tax. " +
      "Include tax if your file's total does. Leave this blank if you don't have one — " +
      "we'll calculate it from price × quantity instead.",
    cost_price_at_sale: "What YOU paid your supplier for this item — not the price you charged the customer.",
    tax_amount: "The tax/VAT charged to the customer, included in your total — lets margin be calculated net of tax.",
    order_reference:
      "Prevents accidentally importing the same order twice if you re-upload a file that overlaps an earlier one.",
    category:
      "Matched against your existing product categories by name, or created if it's new — powers the Category " +
      "Breakdown report and per-category dashboard filters.",
    location: LOCATION_HINT,
  },
  inventory: {
    as_of_date:
      "Most stock-count exports don't have this — leave it blank and we'll use today's date. Only map it if " +
      "your file states the date the count was actually taken (e.g. an overnight export dated for the day before).",
    category:
      "Matched against your existing product categories by name, or created if it's new — powers the Category " +
      "Breakdown report and per-category dashboard filters.",
    location: LOCATION_HINT,
  },
  purchases: {
    purchase_reference:
      "Prevents accidentally importing the same purchase twice if you re-upload a file that overlaps an earlier one.",
    category:
      "Matched against your existing product categories by name, or created if it's new — powers the Category " +
      "Breakdown report and per-category dashboard filters.",
    supplier:
      "Matched against your existing suppliers by name, or created if it's new — powers the Suppliers page's " +
      "spend breakdown and stock-recommendation lead times.",
    location: LOCATION_HINT,
  },
  repairs: {
    labour_cost: "What the job cost YOU in labour — not what you charged the customer.",
    tax_amount: "The tax/VAT charged to the customer, included in the price charged — lets margin be calculated net of tax.",
    repair_reference:
      "Prevents accidentally importing the same repair twice if you re-upload a file that overlaps an earlier one.",
    location: LOCATION_HINT,
  },
};

const NOT_PRESENT = "";

export default function UploadsPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);
  // Uploads/imports 402 without an active subscription (require_active_
  // subscription) — a business pending payment (unsubscribed, or a branch
  // that never finished Checkout) used to still appear as a normal,
  // selectable option in the dropdown below, which looked like a real
  // choice even though nothing there could ever succeed. Fetched here
  // rather than in useBusinessSelector itself, since dashboard/reports
  // deliberately keep showing every business, subscribed or not — only
  // this page's "which business can I actually upload into" question
  // needs filtering.
  const [subscriptions, setSubscriptions] = useState<Record<string, SubscriptionStatus>>({});
  const [subscriptionsLoaded, setSubscriptionsLoaded] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [freshness, setFreshness] = useState<UploadFreshnessEntry[]>([]);
  const [entityType, setEntityType] = useState(ENTITY_TYPES[0].value);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Set on a 402 from either request_upload or run_import
  // (app/billing/access.py::require_active_subscription) — a distinct
  // banner with a real Subscribe action, not just another string in
  // `error`, since "the subscription lapsed" is a whole-business state
  // that deserves a fix, not just a retry.
  const [subscriptionRequired, setSubscriptionRequired] = useState(false);
  const [subscribing, setSubscribing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // The upload currently going through mapping confirmation, if any.
  const [mappingUploadId, setMappingUploadId] = useState<string | null>(null);
  // Which field list/labels to render — the confirmation form never needed
  // to know this before there was only one entity_type.
  const [mappingEntityType, setMappingEntityType] = useState<string>(ENTITY_TYPES[0].value);
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

  // Set when confirm-mapping comes back "needs_location_confirmation"
  // (BD-007 anti-bypass check) — the distinct location values it found in
  // the mapped location column. Rendered as a block-with-override prompt
  // instead of silently saving the mapping.
  const [locationWarning, setLocationWarning] = useState<string[] | null>(null);

  // Per-upload so running/undoing one row's import doesn't disable another's.
  const [runningUploadId, setRunningUploadId] = useState<string | null>(null);
  const [undoingRecordId, setUndoingRecordId] = useState<string | null>(null);
  const [confirmingUndoRecordId, setConfirmingUndoRecordId] = useState<string | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});

  const loadUploads = useCallback((id: string) => {
    apiGet<Upload[]>(`/businesses/${id}/uploads`)
      .then(setUploads)
      .catch(() => undefined);
  }, []);

  const loadFreshness = useCallback((id: string) => {
    apiGet<UploadFreshnessEntry[]>(`/businesses/${id}/uploads/freshness`)
      .then(setFreshness)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (businessId) {
      loadUploads(businessId);
      loadFreshness(businessId);
    }
  }, [businessId, loadUploads, loadFreshness]);

  // Fetched together (Promise.all, not the per-business fire-and-forget
  // pattern used elsewhere) specifically so `subscriptionsLoaded` flips
  // once, not once per business — filtering the dropdown before every
  // response is back would otherwise flash "no subscribed shop" for
  // businesses that are actually fine.
  useEffect(() => {
    if (businesses.length === 0) return;
    setSubscriptionsLoaded(false);
    Promise.all(
      businesses.map((b) =>
        apiGet<SubscriptionStatus>(`/businesses/${b.id}/billing/subscription`)
          .then((s) => [b.id, s] as const)
          .catch(() => [b.id, { status: null, current_period_end: null }] as const)
      )
    ).then((entries) => {
      setSubscriptions(Object.fromEntries(entries));
      setSubscriptionsLoaded(true);
    });
  }, [businesses]);

  const subscribedBusinesses = businesses.filter((b) => subscriptions[b.id]?.status === "active");

  // Once subscriptions are known, a selection that isn't actually
  // subscribed — the default-to-first-business pick from
  // useBusinessSelector landed on an unsubscribed shop, or a stale
  // ?business= link points at one pending payment — is corrected to the
  // first subscribed business instead of silently staying on a dead end.
  useEffect(() => {
    if (!subscriptionsLoaded || subscribedBusinesses.length === 0) return;
    if (!subscribedBusinesses.some((b) => b.id === businessId)) {
      setBusinessId(subscribedBusinesses[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subscriptionsLoaded, subscribedBusinesses, businessId]);

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

  async function startMapping(uploadId: string, uploadEntityType: string, headerRowIndex?: number) {
    setMappingError(null);
    setLocationWarning(null);
    setMappingEntityType(uploadEntityType);
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
          FIELD_ORDER[uploadEntityType].map((field) => [field, result.suggested_mapping[field] ?? NOT_PRESENT])
        )
      );
    } catch (err) {
      setMappingError(
        err instanceof ApiError ? err.message : "Could not read this file's columns. Is the backend running?"
      );
    }
  }

  function handlePickHeaderRow(rowIndex: number) {
    if (mappingUploadId) startMapping(mappingUploadId, mappingEntityType, rowIndex);
  }

  // Shared by the normal submit and the "yes, this really is one location"
  // override button — only the confirm_multiple_locations flag differs
  // between the two (app/imports/service.py::confirm_mapping, BD-007).
  async function submitMapping(confirmMultipleLocations: boolean) {
    if (!mappingUploadId) return;
    setConfirming(true);
    setMappingError(null);
    try {
      const fieldValues = Object.fromEntries(
        FIELD_ORDER[mappingEntityType].map((field) => [field, fieldMapping[field] || null])
      );
      const result = await apiPost<ConfirmMappingResponse>(
        `/businesses/${businessId}/uploads/${mappingUploadId}/confirm-mapping`,
        {
          field_mapping: fieldValues,
          header_row_index: chosenHeaderRowIndex,
          confirm_multiple_locations: confirmMultipleLocations,
        }
      );
      if (result.status === "needs_location_confirmation") {
        // Deliberately does not clear mappingUploadId/detection — the form
        // stays open so the user can either fix the mapping (e.g. unmap
        // location) or use the override button rendered below it.
        setLocationWarning(result.locations ?? []);
        return;
      }
      setLocationWarning(null);
      setNotice("Mapping saved.");
      setMappingUploadId(null);
      setDetection(null);
      setPreviewRows(null);
      setChosenHeaderRowIndex(null);
      loadUploads(businessId);
    } catch (err) {
      // Previously always this one guessed string regardless of the real
      // cause — the backend already returns a specific, accurate detail
      // per failure (missing required fields, a stale/renamed column, the
      // upload already imported, ...); swallowing it here made every
      // failure look like the same "check your mapping" issue even when
      // it wasn't, which is exactly what made a genuinely-correct mapping
      // impossible to debug from this message alone.
      setLocationWarning(null);
      setMappingError(
        err instanceof ApiError
          ? err.message
          : "Could not save this mapping — check that the required fields are mapped."
      );
    } finally {
      setConfirming(false);
    }
  }

  async function handleConfirmMapping(e: React.FormEvent) {
    e.preventDefault();
    await submitMapping(false);
  }

  async function handleConfirmMultipleLocationsOverride() {
    await submitMapping(true);
  }

  async function handleRunImport(uploadId: string) {
    setRunningUploadId(uploadId);
    setActionErrors((prev) => ({ ...prev, [uploadId]: "" }));
    try {
      await apiPost<ImportRunResponse>(`/businesses/${businessId}/uploads/${uploadId}/import`, {});
      loadUploads(businessId);
      loadFreshness(businessId);
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setSubscriptionRequired(true);
      } else {
        setActionErrors((prev) => ({
          ...prev,
          [uploadId]: "Could not run the import. Try again, or check the file hasn't changed.",
        }));
      }
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
      loadFreshness(businessId);
    } catch (err) {
      setActionErrors((prev) => ({
        ...prev,
        [importRecordId]: err instanceof ApiError ? err.message : "Could not undo this import.",
      }));
    } finally {
      setUndoingRecordId(null);
      setConfirmingUndoRecordId(null);
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
      await startMapping(id, entityType);
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setSubscriptionRequired(true);
      } else {
        setError("Upload failed. Make sure the file is a CSV, XLS, or XLSX export.");
      }
    } finally {
      setUploading(false);
    }
  }

  async function handleSubscribeClick() {
    if (!businessId) return;
    setSubscribing(true);
    try {
      await redirectToCheckout(businessId);
    } catch {
      setSubscribing(false);
      setError("Could not start checkout. Try again shortly.");
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

  if (subscriptionsLoaded && subscribedBusinesses.length === 0) {
    // Every business on the account exists but none has an active
    // subscription — the dropdown below only ever offers subscribed
    // shops, so rather than render it empty, name the real reason
    // directly and point at the one place to fix it.
    return (
      <main>
        <AppNav businessId={businessId} />
        <h1>Upload data</h1>
        <p>
          None of your shops has an active subscription yet, so there&apos;s nothing to upload into —{" "}
          <a href="/onboarding">subscribe from Onboarding</a> to start uploading.
        </p>
      </main>
    );
  }

  return (
    <main>
      <AppNav businessId={businessId} />
      <ConfirmDialog
        open={confirmingUndoRecordId !== null}
        title="Undo this import?"
        description="This reverses the records and stock changes created by this upload. It cannot be restored automatically; re-import the file if you need it again."
        confirmLabel="Undo import"
        tone="danger"
        busy={confirmingUndoRecordId !== null && undoingRecordId === confirmingUndoRecordId}
        onCancel={() => setConfirmingUndoRecordId(null)}
        onConfirm={() => confirmingUndoRecordId && handleUndo(confirmingUndoRecordId)}
      />
      <h1>Upload data</h1>

      <section className="upload-guidance" aria-label="Recommended first upload">
        <div>
          <h2>First time here?</h2>
          <p>
            For more accurate results, start with a full year of demand data, then add current stock and recent
            replenishment history.
          </p>
        </div>
        <dl>
          <div>
            <dt>Sales</dt>
            <dd>Last 12 months</dd>
          </div>
          <div>
            <dt>Service / workshop activity</dt>
            <dd>Last 12 months, if the business has service, repair, or workshop revenue</dd>
          </div>
          <div>
            <dt>Current stock / inventory</dt>
            <dd>Latest stock-on-hand file</dd>
          </div>
          <div>
            <dt>Purchases / orders / restocks</dt>
            <dd>Ideally the last 3-12 months</dd>
          </div>
        </dl>
      </section>

      {subscriptionRequired && (
        <p className="status-error">
          This shop&apos;s subscription isn&apos;t active, so uploads and imports are paused.{" "}
          <button type="button" disabled={subscribing} onClick={handleSubscribeClick}>
            {subscribing ? "Starting…" : "Subscribe"}
          </button>
        </p>
      )}

      {freshness.length > 0 && (
        <ul>
          {freshness.map((entry) => {
            const label = ENTITY_TYPES.find((t) => t.value === entry.entity_type)?.label ?? entry.entity_type;
            return (
              <li key={entry.entity_type} className={freshnessClass(entry.last_completed_at)}>
                {label}: {freshnessText(entry.last_completed_at)}
              </li>
            );
          })}
        </ul>
      )}

      {subscribedBusinesses.length > 1 && (
        <div>
          <label htmlFor="business">Business</label>
          <br />
          {/* Only subscribed shops are offered here — a shop pending
              payment (unsubscribed, or a branch that never finished
              Checkout) would 402 on every upload attempt regardless, so
              listing it as a normal, selectable option only invited
              picking a dead end. */}
          <select id="business" value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
            {subscribedBusinesses.map((b) => (
              <option key={b.id} value={b.id}>
                {businessDisplayLabel(b)}
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
          {(mappingEntityType === "sales" || mappingEntityType === "repairs") && (
            <p className="status-warn">
              Prices below split into two sides — what the <strong>customer</strong> paid (price, total, tax)
              versus what <strong>you</strong> paid to get the item or do the job (cost price / labour cost).
              Double-check you haven&apos;t swapped them.
            </p>
          )}
          {FIELD_ORDER[mappingEntityType].map((field) => {
            const selected = fieldMapping[field] ?? "";
            const samples = sampleValuesFor(selected);
            const confidence = confidenceFor(field, selected);
            const needsDoubleCheck = confidence !== null && confidence < HIGH_CONFIDENCE;
            const hint = FIELD_HINTS[mappingEntityType]?.[field];
            return (
              <div key={field}>
                <label htmlFor={`field-${field}`}>
                  {FIELD_LABELS[mappingEntityType][field]}
                  {hint && <span className="hint">{hint}</span>}
                </label>
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
          {locationWarning && (
            <div className="status-warn">
              <p>
                This file looks like it has data from more than one location: {locationWarning.join(", ")}.
                Each additional location is billed separately as its own branch (€30/month) — uploading
                combined data into a single shop instead isn&apos;t supported.
              </p>
              <p>
                <a href="/onboarding">Add a branch</a> for the other location, or if this really is all one
                location — e.g. the column just repeats your shop&apos;s own name or code — confirm below.
              </p>
              <button type="button" disabled={confirming} onClick={handleConfirmMultipleLocationsOverride}>
                {confirming ? "Confirming…" : "Yes, this is genuinely one location"}
              </button>
            </div>
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
              <li className="upload-record" key={u.id}>
                <div className="upload-record__details">
                  {u.original_filename} —{" "}
                  <span className={u.status === "imported" ? "status-ok" : ""}>{u.status}</span>{" "}
                  ({new Date(u.created_at).toLocaleString()})
                </div>
                <div className="upload-record__actions">
                {u.status === "uploaded" && !mappingUploadId && (
                  <button type="button" onClick={() => startMapping(u.id, u.entity_type)}>
                    Map columns
                  </button>
                )}
                {u.status === "mapped" && !mappingUploadId && (
                  <>
                    <button type="button" disabled={isRunning} onClick={() => handleRunImport(u.id)}>
                      {isRunning ? "Running…" : "Run import"}
                    </button>
                    <button type="button" disabled={isRunning} onClick={() => startMapping(u.id, u.entity_type)}>
                      Remap
                    </button>
                  </>
                )}
                </div>
                {record && record.status === "completed" && (
                  <div className="upload-record__result">
                    <span className="status-ok">
                      {record.rows_imported} of {record.rows_total} rows imported
                    </span>
                    {record.rows_rejected > 0 && (
                      <span className="status-warn"> — {record.rows_rejected} skipped</span>
                    )}
                    {renderRejectionSummary(record.rejection_summary)}
                    <div className="upload-record__actions">
                      <button type="button" disabled={isUndoing} onClick={() => setConfirmingUndoRecordId(record.id)}>
                        {isUndoing ? "Undoing…" : "Undo import"}
                      </button>
                    </div>
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

function daysSince(isoTimestamp: string): number {
  const elapsedMs = Date.now() - new Date(isoTimestamp).getTime();
  return Math.floor(elapsedMs / (1000 * 60 * 60 * 24));
}

function freshnessText(lastCompletedAt: string | null): string {
  if (!lastCompletedAt) return "never uploaded";
  const days = daysSince(lastCompletedAt);
  if (days <= 0) return "last uploaded today";
  if (days === 1) return "last uploaded 1 day ago";
  return `last uploaded ${days} days ago`;
}

function freshnessClass(lastCompletedAt: string | null): string {
  if (!lastCompletedAt) return "status-warn";
  return daysSince(lastCompletedAt) > STALE_AFTER_DAYS ? "status-warn" : "";
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
