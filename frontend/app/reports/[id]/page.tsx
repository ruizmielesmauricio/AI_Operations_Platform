"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { apiGet } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { Chart } from "@/components/Chart";
import { CategoryLabel, RecommendationList, Section, Stat } from "@/components/Section";
import { formatMoney, formatPct, formatRate, grossMarginDisplay, workshopMarginDisplay } from "@/lib/format";
import { marginBarOption, revenueForecastLineOption, stockCoverBarOption } from "@/lib/chartOptions";
import { buildFindingByKey, splitRecommendations } from "@/lib/findings";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { CategoryBreakdownRow, DeadStockRow, ProductDemandForecast, ProductMarginRow, ReportDetail, StockCoverRow } from "@/types";

// Stage D17/D18 — a single generated report's full payload. Every
// section mirrors the equivalent frontend/app/dashboard/page.tsx section
// (same Chart/Section/Stat building blocks, same schemas) because the
// backend payload literally reuses the dashboard's own Pydantic schemas
// to serialize each section — a report and the live dashboard can never
// disagree about a number's shape (see app/application/report.py).
export default function ReportDetailPage() {
  const { session, checkingSession } = useRequireSession();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const businessId = searchParams.get("business") ?? "";

  const [report, setReport] = useState<ReportDetail | null>(null);
  const [error, setError] = useState<string | undefined>();

  useEffect(() => {
    if (!businessId || !params.id) return;
    setError(undefined);
    apiGet<ReportDetail>(`/businesses/${businessId}/reports/${params.id}`)
      .then(setReport)
      .catch(() => setError("Could not load this report — it may have expired or no longer exists."));
  }, [businessId, params.id]);

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
        <h1>Report</h1>
        <p>
          No business selected — go back to <a href="/reports">Reports</a>.
        </p>
      </main>
    );
  }

  return (
    <main className="wide">
      <AppNav businessId={businessId} />
      {error && <p className="status-error">{error}</p>}
      {!error && !report && <p>Loading…</p>}
      {!error && report && report.payload && <ReportView report={report} payload={report.payload} />}
    </main>
  );
}

function ReportView({ report, payload }: { report: ReportDetail; payload: NonNullable<ReportDetail["payload"]> }) {
  const { executive_summary: summary, financial_performance: financial, retail_operations: retail, inventory_health: inventory, forecast, findings, workshop_performance: workshop, category_breakdown: categoryBreakdown } = payload;
  const marginRows = dedupeByProduct([...financial.bottom_margin_products, ...financial.top_margin_products]);
  const withCover = retail.stock_cover.filter((r) => r.cover_days !== null);
  // A report's comparison window is always exactly one prior period of
  // the same length (WoW for weekly, MoM for monthly) — unlike the
  // dashboard's arbitrary user-chosen date range, this can be stated
  // concretely rather than left as a generic "previous period."
  const trendLabel = payload.report_type === "weekly" ? "last week" : "last month";
  const grossMargin = grossMarginDisplay(financial.gross_margin, financial.revenue.current);

  // Findings.findings/recommendations may be absent on a report stored
  // before this pairing existed — same defensive-guard reasoning as
  // financial.returns/categoryBreakdown below (a report payload is a
  // JSON snapshot, never re-serialized against a later schema).
  const findingByKey = buildFindingByKey(findings?.findings ?? []);
  const { businessWide, stockAndProducts } = splitRecommendations(findings?.recommendations ?? []);

  const sections: { id: string; title: string }[] = [
    { id: "executive-summary", title: "Executive Summary" },
    { id: "revenue-performance", title: "Revenue Performance" },
    { id: "sales-performance", title: "Sales Performance" },
    { id: "category-breakdown", title: "Category Breakdown" },
    { id: "inventory-health", title: "Inventory Health" },
    { id: "forecast-outlook", title: "Forecast & Future Outlook" },
    { id: "purchasing-recommendations", title: "Purchasing Recommendations" },
    ...(workshop ? [{ id: "workshop-performance", title: "Workshop Performance" }] : []),
    { id: "action-plan", title: "Action Plan" },
  ];

  return (
    <>
      <div className="no-print" style={{ float: "right" }}>
        <button type="button" onClick={() => window.print()}>
          Download PDF
        </button>
      </div>
      <h1>
        {payload.report_type === "weekly" ? "Weekly" : "Monthly"} Report — {payload.business_name}
      </h1>
      <p className="hint">
        {formatDate(payload.period_start)} – {formatDate(payload.period_end)} · generated {formatDate(payload.generated_at)} ·
        available until {report.expires_at ? formatDate(report.expires_at) : "—"}
      </p>
      <p className="hint">
        Not AI — every figure below comes from the same deterministic calculations behind the live dashboard.
      </p>

      <nav aria-label="Report sections">
        <strong>Sections:</strong>{" "}
        {sections.map((s, i) => (
          <span key={s.id}>
            {i > 0 && " · "}
            <a href={`#${s.id}`}>{s.title}</a>
          </span>
        ))}
      </nav>

      <Section id="executive-summary" title="Executive Summary">
        <ul>
          {summary.narrative.map((sentence, i) => (
            <li key={i}>{sentence}</li>
          ))}
        </ul>
        <Stat label="Revenue" value={formatMoney(financial.revenue.current)} trendPct={financial.revenue.change_pct} trendLabel={trendLabel} />
        <Stat label="Transactions" value={String(summary.transactions)} />
        <Stat label="Average sale" value={summary.average_sale !== null ? formatMoney(summary.average_sale) : "—"} />
        <Stat label="Gross margin" value={grossMargin.value} note={grossMargin.note} />
        <Stat label="Inventory value" value={formatMoney(retail.inventory_value.value_at_cost)} />
        <Stat label="Low stock" value={String(summary.low_stock_count)} />
        <Stat label="Dead stock" value={String(summary.dead_stock_count)} />

        {summary.top_recommendations.length > 0 && (
          <>
            <h3>Top recommendations</h3>
            <RecommendationList recommendations={summary.top_recommendations} findingByKey={findingByKey} showCategory={true} />
          </>
        )}
      </Section>

      <Section id="revenue-performance" title="Revenue Performance">
        <Stat label="Revenue" value={formatMoney(financial.revenue.current)} trendPct={financial.revenue.change_pct} trendLabel={trendLabel} />
        {/* financial.returns may be absent on a report stored before that
            field was added — a report payload is a JSON snapshot from
            generation time, never re-serialized against a later schema,
            so any schema addition needs this same defensive guard rather
            than assuming every stored report matches today's shape. */}
        {financial.returns && Number(financial.returns.returns_amount) > 0 && (
          <p className="hint">
            Includes {financial.returns.return_count} return{financial.returns.return_count === 1 ? "" : "s"}{" "}
            totaling {formatMoney(financial.returns.returns_amount)} — already netted out of the revenue above
            (gross revenue before returns: {formatMoney(financial.returns.gross_revenue)}).
          </p>
        )}
        <Stat label="Gross margin" value={grossMargin.value} note={grossMargin.note} />
        {marginRows.length > 0 ? (
          <Chart option={marginBarOption(marginRows, "Gross profit by product (€)")} />
        ) : (
          <p>No product margin data for this period.</p>
        )}
      </Section>

      <Section id="sales-performance" title="Sales Performance">
        <TopSellersTable title="Top sellers by units" rows={retail.top_sellers_by_units} />
        <TopSellersTable title="Top sellers by revenue" rows={retail.top_sellers_by_revenue} />
      </Section>

      <Section id="category-breakdown" title="Category Breakdown">
        <p className="hint">
          Revenue, expenses, and stock value per product category. Expenses is purchase cost (what you paid
          buying stock), not cost of goods sold — a different figure from Gross margin above. Stock value here is
          at sell price, not cost — a different figure from Inventory value below. Products with no category set
          are grouped under &quot;Uncategorized.&quot;
        </p>
        {/* categoryBreakdown may be absent on a report stored before this
            feature shipped — same defensive guard as financial.returns
            above, see that comment. */}
        {!categoryBreakdown || categoryBreakdown.rows.length === 0 ? (
          <p>No category data for this period.</p>
        ) : (
          <CategoryBreakdownTable rows={categoryBreakdown.rows} />
        )}
      </Section>

      <Section id="inventory-health" title="Inventory Health">
        <Stat label="Inventory value" value={formatMoney(retail.inventory_value.value_at_cost)} />
        <Stat label="Sell-through rate" value={formatRate(retail.sell_through_rate)} />
        <Stat label="Inventory turnover" value={inventory.turnover_ratio !== null ? `${inventory.turnover_ratio}x` : "—"} />

        <h3>Stock cover</h3>
        {withCover.length > 0 ? (
          <Chart option={stockCoverBarOption(withCover)} />
        ) : (
          <p>Not enough recent sales to estimate stock cover.</p>
        )}

        <h3>Fast movers</h3>
        <p className="hint">Products selling through quickly (14 days of cover or less).</p>
        {inventory.fast_movers.length > 0 ? (
          <StockRowsTable rows={inventory.fast_movers} />
        ) : (
          <p>None this period.</p>
        )}

        <h3>Slow movers</h3>
        <p className="hint">Products with 60+ days of cover — consider a discount, bundle, or supplier return.</p>
        {inventory.slow_movers.length > 0 ? (
          <StockRowsTable rows={inventory.slow_movers} />
        ) : (
          <p>None this period.</p>
        )}

        <h3>Dead stock</h3>
        <p className="hint">
          Products with stock on hand but zero sales this period at all — even less recent activity than Slow
          Movers above, which at least still have a measurable (if slow) cover figure. Worth investigating before
          reordering more, and a candidate for a discount, bundle, or supplier return.
        </p>
        {retail.dead_stock.length === 0 ? (
          <p>None — every product with stock on hand sold at least once this period.</p>
        ) : (
          <DeadStockTable rows={retail.dead_stock} />
        )}
      </Section>

      <Section id="forecast-outlook" title="Forecast & Future Outlook">
        <p className="hint">
          A plain projection from recent sales history — not AI, not a formal statistical guarantee.
        </p>
        {forecast.revenue.result.insufficient_data ? (
          <p>Not enough sales history yet to forecast revenue.</p>
        ) : (
          <>
            <Stat
              label={`Expected revenue, next ${forecast.horizon_days} days`}
              value={`${formatMoney(forecast.revenue.result.total_point)} (typically ${formatMoney(forecast.revenue.result.total_low)}–${formatMoney(forecast.revenue.result.total_high)})`}
            />
            <Chart option={revenueForecastLineOption(forecast.revenue.result.daily)} />
          </>
        )}
      </Section>

      <Section id="purchasing-recommendations" title="Purchasing Recommendations">
        {forecast.products.length === 0 ? (
          <p>No products have enough sales history yet to forecast demand.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>Current stock</th>
                <th>Forecast demand</th>
                <th>Cover left</th>
                <th>Suggested reorder</th>
              </tr>
            </thead>
            <tbody>
              {forecast.products.map((row: ProductDemandForecast) => (
                <tr key={row.product_id}>
                  <td>
                    {row.name}
                    <CategoryLabel name={row.category_name} />
                  </td>
                  <td>{row.current_stock}</td>
                  <td>
                    {row.result.total_point} ({row.result.total_low}–{row.result.total_high})
                  </td>
                  <td>{row.days_of_cover_at_forecast_rate !== null ? `${row.days_of_cover_at_forecast_rate}d` : "—"}</td>
                  <td>{row.suggested_reorder_quantity > 0 ? row.suggested_reorder_quantity : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {workshop && (
        <Section id="workshop-performance" title="Workshop Performance">
          <Stat label="Repairs completed" value={String(workshop.margin.repair_count)} />
          <Stat label="Revenue" value={formatMoney(workshop.revenue.current)} trendPct={workshop.revenue.change_pct} trendLabel={trendLabel} />
          <Stat
            label="Average ticket"
            value={workshop.margin.average_ticket !== null ? formatMoney(workshop.margin.average_ticket) : "—"}
          />
          <Stat
            label="Gross margin (labour only)"
            value={workshopMarginDisplay(workshop.margin).value}
            note={workshopMarginDisplay(workshop.margin).note}
          />
        </Section>
      )}

      <Section id="action-plan" title="Action Plan">
        {businessWide.length === 0 && stockAndProducts.length === 0 ? (
          <p>Nothing to flag for this period.</p>
        ) : (
          <>
            {businessWide.length > 0 && (
              <>
                <h3>Business performance</h3>
                <RecommendationList recommendations={businessWide} findingByKey={findingByKey} showCategory={false} />
              </>
            )}
            {stockAndProducts.length > 0 && (
              <>
                <h3>Stock &amp; products</h3>
                <RecommendationList recommendations={stockAndProducts} findingByKey={findingByKey} showCategory={true} />
              </>
            )}
          </>
        )}
      </Section>
    </>
  );
}

function TopSellersTable({
  title,
  rows,
}: {
  title: string;
  rows: { product_id: string; name: string; units_sold: number; revenue: string; category_name: string | null }[];
}) {
  return (
    <>
      <h3>{title}</h3>
      {rows.length === 0 ? (
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
            {rows.slice(0, 5).map((row) => (
              <tr key={row.product_id}>
                <td>
                  {row.name}
                  <CategoryLabel name={row.category_name} />
                </td>
                <td>{row.units_sold}</td>
                <td>{formatMoney(row.revenue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function StockRowsTable({ rows }: { rows: StockCoverRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Product</th>
          <th>Stock on hand</th>
          <th>Cover left</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.product_id}>
            <td>
              {row.name}
              <CategoryLabel name={row.category_name} />
            </td>
            <td>{row.stock_on_hand}</td>
            <td>{row.cover_days !== null ? `${row.cover_days}d` : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
            <td>
              {row.name}
              <CategoryLabel name={row.category_name} />
            </td>
            <td>{row.stock_on_hand}</td>
            <td>{row.value_at_cost !== null ? formatMoney(row.value_at_cost) : "unknown"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CategoryBreakdownTable({ rows }: { rows: CategoryBreakdownRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th>Revenue</th>
          <th>Expenses</th>
          <th>Stock value (at sell price)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.category_id ?? "uncategorized"}>
            <td>{row.category_name}</td>
            <td>{formatMoney(row.revenue)}</td>
            <td>
              {formatMoney(row.expenses)}
              {row.expenses_data_coverage_pct !== null && Number(row.expenses_data_coverage_pct) < 100 && (
                <>
                  {" "}
                  <span className="hint">(only {formatPct(row.expenses_data_coverage_pct)} of purchased quantity has a known cost)</span>
                </>
              )}
            </td>
            <td>
              {formatMoney(row.stock_value)}
              {row.products_excluded_from_stock_value > 0 && (
                <>
                  {" "}
                  <span className="hint">({row.products_excluded_from_stock_value} product(s) excluded — no sell price)</span>
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function dedupeByProduct(rows: ProductMarginRow[]): ProductMarginRow[] {
  const byId = new Map(rows.map((r) => [r.product_id, r]));
  return Array.from(byId.values());
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString();
}
