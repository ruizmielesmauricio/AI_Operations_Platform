"use client";

import { useEffect, useState } from "react";
import type { EChartsOption } from "echarts";
import { apiGet } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { Chart } from "@/components/Chart";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type {
  Alert,
  DeadStockRow,
  Finding,
  Findings,
  FinancialPerformance,
  ProductMarginRow,
  Recommendation,
  RetailOperations,
  StockCoverRow,
  WorkshopPerformance,
} from "@/types";

// PR-3.7 — plain-language definitions on demand. Static strings for now;
// a fetched "Business Knowledge" definitions API doesn't exist yet.
const DEFINITIONS: Record<string, string> = {
  revenue: "Total sales recorded in the selected period.",
  grossMargin: "Revenue minus the cost of goods sold, as a percentage of revenue with a known cost.",
  costCoverage: "Share of revenue where a cost price was actually recorded — margin below this is only an estimate.",
  stockCover: "How many days of stock are left at the recent sales rate. Blank means not enough recent sales to estimate.",
  deadStock: "Products with stock on hand but zero sales in the selected period.",
  sellThrough: "Units sold divided by units sold plus stock still on hand — an approximation, not an exact sell-through rate.",
  workshopMargin: "Price charged minus labour cost. Parts cost isn't tracked yet, so this understates true repair cost.",
};

type SectionKey = "financial" | "retail" | "workshop" | "findings" | "alerts";

export default function DashboardPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);

  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const [financial, setFinancial] = useState<FinancialPerformance | null>(null);
  const [retail, setRetail] = useState<RetailOperations | null>(null);
  const [workshop, setWorkshop] = useState<WorkshopPerformance | null>(null);
  const [findings, setFindings] = useState<Findings | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [errors, setErrors] = useState<Partial<Record<SectionKey, string>>>({});

  useEffect(() => {
    if (!businessId) return;
    const qs = periodQuery(startDate, endDate);
    setErrors({});

    apiGet<FinancialPerformance>(`/businesses/${businessId}/analytics/financial-performance${qs}`)
      .then(setFinancial)
      .catch(() => setErrors((prev) => ({ ...prev, financial: "Could not load financial performance." })));

    apiGet<RetailOperations>(`/businesses/${businessId}/analytics/retail-operations${qs}`)
      .then(setRetail)
      .catch(() => setErrors((prev) => ({ ...prev, retail: "Could not load retail operations." })));

    apiGet<WorkshopPerformance>(`/businesses/${businessId}/analytics/workshop-performance${qs}`)
      .then(setWorkshop)
      .catch(() => setErrors((prev) => ({ ...prev, workshop: "Could not load workshop performance." })));

    apiGet<Findings>(`/businesses/${businessId}/analytics/findings${qs}`)
      .then(setFindings)
      .catch(() => setErrors((prev) => ({ ...prev, findings: "Could not load findings." })));

    // Alerts aren't period-scoped (they're the current active set), unlike
    // the four analytics endpoints above.
    apiGet<Alert[]>(`/businesses/${businessId}/alerts`)
      .then(setAlerts)
      .catch(() => setErrors((prev) => ({ ...prev, alerts: "Could not load alerts." })));
  }, [businessId, startDate, endDate]);

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
        <h1>Dashboard</h1>
        <p>
          No business yet — <a href="/onboarding">create one first</a>.
        </p>
      </main>
    );
  }

  return (
    <main className="wide">
      <AppNav businessId={businessId} />
      <h1>Dashboard</h1>

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

      <div>
        <label htmlFor="start-date">From</label>{" "}
        <input id="start-date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />{" "}
        <label htmlFor="end-date">to</label>{" "}
        <input id="end-date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />{" "}
        {(startDate || endDate) && (
          <button
            type="button"
            onClick={() => {
              setStartDate("");
              setEndDate("");
            }}
          >
            Reset to default (last 30 days)
          </button>
        )}
      </div>

      <FinancialSection data={financial} error={errors.financial} />
      <RetailSection data={retail} error={errors.retail} />
      <WorkshopSection data={workshop} error={errors.workshop} />
      <FindingsSection data={findings} error={errors.findings} />
      <AlertsSection alerts={alerts} error={errors.alerts} />
    </main>
  );
}

// --- Financial Performance ---------------------------------------------

function FinancialSection({ data, error }: { data: FinancialPerformance | null; error?: string }) {
  if (error) return <Section title="Financial Performance"><p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Financial Performance"><p>Loading…</p></Section>;

  const { revenue, gross_margin: grossMargin } = data;
  const marginRows = dedupeByProduct([...data.bottom_margin_products, ...data.top_margin_products]);

  return (
    <Section title="Financial Performance">
      <Stat label="Revenue" title={DEFINITIONS.revenue} value={formatMoney(revenue.current)} trendPct={revenue.change_pct} />
      <Stat
        label="Gross margin"
        title={DEFINITIONS.grossMargin}
        value={formatPct(grossMargin.gross_margin_pct)}
        note={
          grossMargin.cost_data_coverage_pct !== null
            ? `based on ${formatPct(grossMargin.cost_data_coverage_pct)} of revenue with known cost`
            : "no cost data recorded yet"
        }
        noteTitle={DEFINITIONS.costCoverage}
      />
      {data.products_excluded_from_ranking > 0 && (
        <p className="status-warn">
          {data.products_excluded_from_ranking} product(s) excluded from ranking — no recorded cost price.
        </p>
      )}
      {marginRows.length > 0 ? (
        <Chart option={marginBarOption(marginRows, "Gross profit by product (€)")} />
      ) : (
        <p>No product margin data for this period.</p>
      )}
    </Section>
  );
}

// --- Retail Operations ---------------------------------------------------

function RetailSection({ data, error }: { data: RetailOperations | null; error?: string }) {
  if (error) return <Section title="Retail Operations"><p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Retail Operations"><p>Loading…</p></Section>;

  const withCover = data.stock_cover.filter((r) => r.cover_days !== null);
  const noRecentSales = data.stock_cover.filter((r) => r.cover_days === null && r.stock_on_hand > 0);

  return (
    <Section title="Retail Operations">
      <Stat label="Inventory value" value={formatMoney(data.inventory_value.value_at_cost)} />
      <Stat label="Sell-through rate" title={DEFINITIONS.sellThrough} value={formatRate(data.sell_through_rate)} />

      <h3>Top sellers</h3>
      {data.top_sellers.length === 0 ? (
        <p>No sales in this period.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Product</th>
              <th>Units sold</th>
              <th>Revenue</th>
            </tr>
          </thead>
          <tbody>
            {data.top_sellers.map((row) => (
              <tr key={row.product_id}>
                <td>{row.name}</td>
                <td>{row.units_sold}</td>
                <td>{formatMoney(row.revenue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3 title={DEFINITIONS.stockCover}>Stock cover</h3>
      {withCover.length > 0 ? (
        <Chart option={stockCoverBarOption(withCover)} />
      ) : (
        <p>Not enough recent sales to estimate stock cover.</p>
      )}
      {noRecentSales.length > 0 && (
        <p className="status-warn">
          {noRecentSales.length} product(s) have stock but no recent sales, so cover can&apos;t be estimated —
          see Dead Stock below.
        </p>
      )}

      <h3 title={DEFINITIONS.deadStock}>Dead stock</h3>
      {data.dead_stock.length === 0 ? (
        <p>None — every product with stock on hand sold at least once this period.</p>
      ) : (
        <DeadStockTable rows={data.dead_stock} />
      )}
    </Section>
  );
}

function DeadStockTable({ rows }: { rows: DeadStockRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Product</th>
          <th>Stock on hand</th>
          <th>Value at cost</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.product_id}>
            <td>{row.name}</td>
            <td>{row.stock_on_hand}</td>
            <td>{row.value_at_cost !== null ? formatMoney(row.value_at_cost) : "unknown"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// --- Workshop Performance --------------------------------------------------

function WorkshopSection({ data, error }: { data: WorkshopPerformance | null; error?: string }) {
  if (error) return <Section title="Workshop Performance"><p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Workshop Performance"><p>Loading…</p></Section>;

  const { revenue, margin } = data;

  return (
    <Section title="Workshop Performance">
      <Stat label="Repairs completed" value={String(margin.repair_count)} />
      <Stat label="Revenue" value={formatMoney(revenue.current)} trendPct={revenue.change_pct} />
      <Stat label="Average ticket" value={margin.average_ticket !== null ? formatMoney(margin.average_ticket) : "—"} />
      <Stat
        label="Gross margin (labour only)"
        title={DEFINITIONS.workshopMargin}
        value={formatPct(margin.gross_margin_pct)}
        note={
          margin.labour_cost_coverage_pct !== null
            ? `based on ${formatPct(margin.labour_cost_coverage_pct)} of revenue with known labour cost — parts cost not tracked yet`
            : "no labour cost recorded yet"
        }
      />
      {margin.revenue_coverage_pct !== null && Number(margin.revenue_coverage_pct) < 100 && (
        <p className="status-warn">
          Only {formatPct(margin.revenue_coverage_pct)} of repairs have a recorded price — revenue may understate
          actual work done.
        </p>
      )}
    </Section>
  );
}

// --- Findings & Recommendations -------------------------------------------

function FindingsSection({ data, error }: { data: Findings | null; error?: string }) {
  if (error) return <Section title="Findings & Recommendations"><p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Findings & Recommendations"><p>Loading…</p></Section>;
  if (data.recommendations.length === 0) {
    return (
      <Section title="Findings & Recommendations">
        <p>Nothing to flag for this period.</p>
      </Section>
    );
  }

  const findingByKey = new Map(data.findings.map((f) => [findingKey(f.type, f.evidence), f]));

  return (
    <Section title="Findings & Recommendations">
      <ul>
        {data.recommendations.map((rec, index) => {
          const finding = findingByKey.get(findingKey(rec.finding_type, rec.evidence));
          return (
            <li key={index} className={severityClass(rec.severity)}>
              <strong>{rec.title}</strong>
              {finding && <> — {finding.message}</>}
              <br />
              <span>{rec.description}</span>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

// Recommendation.evidence is the same dict as its source Finding.evidence
// (assigned directly on the backend), so matching on finding_type plus the
// per-product evidence key (when present) reliably pairs a recommendation
// back to the finding it explains — the two lists are sorted differently
// (recommendations by severity/impact, findings by evaluation order), so a
// positional zip would pair them incorrectly.
function findingKey(type: string, evidence: Record<string, unknown>): string {
  return `${type}:${evidence.product_id ?? ""}`;
}

// --- Alerts ----------------------------------------------------------------

function AlertsSection({ alerts, error }: { alerts: Alert[]; error?: string }) {
  if (error) return <Section title="Active Alerts"><p className="status-error">{error}</p></Section>;
  if (alerts.length === 0) {
    return (
      <Section title="Active Alerts">
        <p>No active alerts.</p>
      </Section>
    );
  }

  return (
    <Section title="Active Alerts">
      <ul>
        {alerts.map((alert) => (
          <li key={alert.id} className={severityClass(alert.payload.severity)}>
            {alert.payload.message}
          </li>
        ))}
      </ul>
    </Section>
  );
}

// --- Shared layout / formatting helpers -------------------------------------

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  title,
  trendPct,
  note,
  noteTitle,
}: {
  label: string;
  value: string;
  title?: string;
  trendPct?: string | null;
  note?: string;
  noteTitle?: string;
}) {
  return (
    <div>
      <span title={title}>{label}</span>: <strong>{value}</strong>
      {trendPct !== undefined && trendPct !== null && (
        <span className={Number(trendPct) >= 0 ? "status-ok" : "status-error"}>
          {" "}
          ({Number(trendPct) >= 0 ? "+" : ""}
          {trendPct}% vs previous period)
        </span>
      )}
      {note && <span title={noteTitle}> — {note}</span>}
    </div>
  );
}

function periodQuery(start: string, end: string): string {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

function formatMoney(value: string): string {
  const n = Number(value);
  return `€${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPct(value: string | null): string {
  return value !== null ? `${value}%` : "—";
}

function formatRate(value: string | null): string {
  return value !== null ? `${(Number(value) * 100).toFixed(1)}%` : "—";
}

function severityClass(severity: string): string {
  if (severity === "critical") return "status-error";
  if (severity === "warning") return "status-warn";
  return "status-info";
}

function dedupeByProduct(rows: ProductMarginRow[]): ProductMarginRow[] {
  const byId = new Map(rows.map((r) => [r.product_id, r]));
  return Array.from(byId.values());
}

function marginBarOption(rows: ProductMarginRow[], title: string): EChartsOption {
  const sorted = [...rows].sort((a, b) => Number(a.gross_profit) - Number(b.gross_profit));
  return {
    title: { text: title, textStyle: { fontSize: 13 } },
    grid: { left: 140, right: 30, top: 40, bottom: 20 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: sorted.map((r) => r.name) },
    series: [
      {
        type: "bar",
        data: sorted.map((r) => {
          const value = Number(r.gross_profit);
          return { value, itemStyle: { color: value < 0 ? "#cf222e" : "#1a7f37" } };
        }),
      },
    ],
  };
}

function stockCoverBarOption(rows: StockCoverRow[]): EChartsOption {
  const sorted = [...rows]
    .sort((a, b) => Number(a.cover_days) - Number(b.cover_days))
    .slice(0, 15);
  return {
    grid: { left: 140, right: 30, top: 20, bottom: 20 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", name: "Days of stock left" },
    yAxis: { type: "category", data: sorted.map((r) => r.name) },
    series: [
      {
        type: "bar",
        data: sorted.map((r) => {
          const value = Number(r.cover_days);
          return { value, itemStyle: { color: value <= 7 ? "#cf222e" : "#0969da" } };
        }),
      },
    ],
  };
}
