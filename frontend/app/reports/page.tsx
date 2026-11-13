"use client";

import { useEffect, useState } from "react";
import { ApiError, apiGet, apiPost } from "@/lib/api/client";
import { businessDisplayLabel } from "@/lib/businessLabel";
import { AppNav } from "@/components/AppNav";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import { formatDate, formatPeriodEnd } from "@/lib/format";
import type { ReportSummary } from "@/types";

// Stage D17/D18 — lists the weekly/monthly reports the scheduler
// (app/scheduler/tick.py) has generated for the selected business.
// Completed-and-not-yet-expired only, newest first (PR-8.5's seven-day
// window) — matches exactly what GET .../reports returns, no
// client-side filtering.
export default function ReportsPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);

  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [error, setError] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [notice, setNotice] = useState<string | undefined>();
  const role = businesses.find((b) => b.id === businessId)?.role;
  const canGenerate = role === "owner" || role === "manager";

  // On-demand: builds the latest completed weekly + monthly reports from
  // today's data instead of waiting for the scheduler (found live: a new
  // business saw an empty page). Never creates duplicates — it refreshes
  // the same report for each period.
  async function handleGenerateNow() {
    setGenerating(true);
    setError(undefined);
    setNotice(undefined);
    try {
      const fresh = await apiPost<ReportSummary[]>(`/businesses/${businessId}/reports/generate-now`, {});
      setReports(fresh);
      setNotice("Reports updated with your latest data.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate reports.");
    } finally {
      setGenerating(false);
    }
  }

  useEffect(() => {
    if (!businessId) return;
    setLoading(true);
    setError(undefined);
    apiGet<ReportSummary[]>(`/businesses/${businessId}/reports`)
      .then(setReports)
      .catch(() => setError("Could not load reports."))
      .finally(() => setLoading(false));
  }, [businessId]);

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
        <h1>Reports</h1>
        <p>
          No business yet — <a href="/onboarding">create one first</a>.
        </p>
      </main>
    );
  }

  return (
    <main className="wide">
      <AppNav businessId={businessId} />
      <h1>Reports</h1>
      <p className="hint">
        Automatically generated every Monday (weekly) and on the 1st of the month (monthly), covering the previous
        completed period. No AI — every number here traces to the same deterministic calculations behind the
        dashboard. Reports stay available for 7 days after generation.
      </p>

      {businesses.length > 1 && (
        <div>
          <label htmlFor="business">Business</label>
          <br />
          <select id="business" value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {businessDisplayLabel(b)}
              </option>
            ))}
          </select>
        </div>
      )}

      {canGenerate && (
        <p>
          <button type="button" disabled={generating || !businessId} onClick={handleGenerateNow}>
            {generating ? "Generating…" : reports.length === 0 ? "Generate reports now" : "Refresh reports with latest data"}
          </button>{" "}
          <span className="hint">Builds last week&apos;s and last month&apos;s reports from the data uploaded so far.</span>
        </p>
      )}
      {notice && <p className="status-ok">{notice}</p>}
      {error && <p className="status-error">{error}</p>}
      {!error && loading && <p>Loading…</p>}
      {!error && !loading && reports.length === 0 && (
        <p>
          No reports yet.{" "}
          {canGenerate
            ? "Use the button above to create them now, or wait for the next automatic run."
            : "They appear automatically after the first completed week or month, or an owner/manager can generate them now."}
        </p>
      )}
      {!error && reports.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Period</th>
              <th>Generated</th>
              <th>Available until</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.id}>
                <td>{r.report_type === "weekly" ? "Weekly" : "Monthly"}</td>
                <td>
                  {formatDate(r.period_start)} – {formatPeriodEnd(r.period_end)}
                </td>
                <td>{formatDate(r.created_at)}</td>
                <td>{r.expires_at ? formatDate(r.expires_at) : "—"}</td>
                <td>
                  <a href={`/reports/${r.id}?business=${businessId}`}>View</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

