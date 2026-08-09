"use client";

import { useEffect, useState } from "react";
import { ApiError, apiGet } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { Chart } from "@/components/Chart";
import { CategoryLabel, RecommendationList, Section, Stat } from "@/components/Section";
import { formatMoney, formatPct, formatRate, grossMarginDisplay, severityClass, workshopMarginDisplay } from "@/lib/format";
import { marginBarOption, revenueForecastLineOption, stockCoverBarOption } from "@/lib/chartOptions";
import { buildFindingByKey, splitRecommendations } from "@/lib/findings";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type {
  Alert,
  DeadStockRow,
  Findings,
  FinancialPerformance,
  Forecast,
  ProductCategory,
  ProductDemandForecast,
  ProductMarginRow,
  ProductSalesRow,
  RetailOperations,
  WorkshopPerformance,
} from "@/types";

// PR-3.7 — plain-language definitions on demand. Static strings for now;
// a fetched "Business Knowledge" definitions API doesn't exist yet.
const DEFINITIONS: Record<string, string> = {
  revenue: "Total sales recorded in the selected period.",
  returns: "Sales rows with a negative quantity — returns/refunds — are counted as returns, not sales, and already netted out of revenue.",
  grossMargin: "Revenue minus the cost of goods sold, as a percentage of revenue with a known cost.",
  costCoverage: "Share of revenue where a cost price was actually recorded — margin below this is only an estimate.",
  taxCoverage: "Share of cost-known revenue that also has a confirmed tax figure, letting margin be computed net of tax rather than assumed.",
  stockCover: "How many days of stock are left at the recent sales rate. Blank means not enough recent sales to estimate.",
  sellThrough: "Units sold divided by units sold plus stock still on hand — an approximation, not an exact sell-through rate.",
  workshopMargin: "Price charged minus labour cost. Parts cost isn't tracked yet, so this understates true repair cost.",
  revenueForecast:
    "A simple projection from recent sales history (same weekday pattern, or a plain average if there isn't enough history yet) — not AI, just deterministic math. The shaded range is a typical spread, not a guarantee.",
  reorderSuggestion:
    "A starting suggestion only: forecasted demand's upper estimate minus current stock. Doesn't account for supplier lead time or safety stock.",
};

type SectionKey = "financial" | "retail" | "workshop" | "findings" | "alerts" | "forecast";

export default function DashboardPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);

  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  // Direct request: combine every section across this business's whole
  // standalone-shop-plus-branches group into one view. Only offered when
  // there's more than one business at all — the one-shop-per-account
  // limit guarantees `businesses` here IS exactly that group already (no
  // separate "which businesses form a group" question to ask). Backend
  // additionally requires every business in the group to share one
  // timezone (app/application/business_group.py) — surfaced as a plain
  // 409 error below, not silently worked around.
  const [allBranches, setAllBranches] = useState(false);

  const [financial, setFinancial] = useState<FinancialPerformance | null>(null);
  const [retail, setRetail] = useState<RetailOperations | null>(null);
  const [workshop, setWorkshop] = useState<WorkshopPerformance | null>(null);
  const [findings, setFindings] = useState<Findings | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [horizonDays, setHorizonDays] = useState(7);
  const [errors, setErrors] = useState<Partial<Record<SectionKey, string>>>({});

  // One dropdown per relevant section (not a shared/global control), per
  // direct instruction. Workshop Performance has no category filter —
  // repairs have no product link at all. Forecast's per-product table and
  // Findings' per-product rules are both filterable too; Forecast's own
  // revenue-forecast figure and Findings' whole-business rules
  // (revenue decline, low margin, incomplete cost data, high return
  // rate) stay unfiltered regardless — see their own backend comments.
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [financialCategoryId, setFinancialCategoryId] = useState("");
  const [retailCategoryId, setRetailCategoryId] = useState("");
  const [findingsCategoryId, setFindingsCategoryId] = useState("");
  const [forecastCategoryId, setForecastCategoryId] = useState("");

  useEffect(() => {
    if (!businessId) return;
    apiGet<ProductCategory[]>(`/businesses/${businessId}/product-categories`)
      .then(setCategories)
      .catch(() => setCategories([]));
  }, [businessId]);

  useEffect(() => {
    if (!businessId) return;
    setErrors({});

    apiGet<FinancialPerformance>(
      `/businesses/${businessId}/analytics/financial-performance${periodQuery(startDate, endDate, financialCategoryId, allBranches)}`
    )
      .then(setFinancial)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, financial: sectionErrorMessage(err, "Could not load financial performance.") }))
      );

    apiGet<RetailOperations>(
      `/businesses/${businessId}/analytics/retail-operations${periodQuery(startDate, endDate, retailCategoryId, allBranches)}`
    )
      .then(setRetail)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, retail: sectionErrorMessage(err, "Could not load retail operations.") }))
      );

    apiGet<WorkshopPerformance>(
      `/businesses/${businessId}/analytics/workshop-performance${periodQuery(startDate, endDate, undefined, allBranches)}`
    )
      .then(setWorkshop)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, workshop: sectionErrorMessage(err, "Could not load workshop performance.") }))
      );

    apiGet<Findings>(
      `/businesses/${businessId}/analytics/findings${periodQuery(startDate, endDate, findingsCategoryId, allBranches)}`
    )
      .then(setFindings)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, findings: sectionErrorMessage(err, "Could not load findings.") }))
      );

    // Alerts aren't period-scoped (they're the current active set), unlike
    // the four analytics endpoints above — and not combined across
    // branches either: an alert is already tied to one business's own
    // stock, so "all branches" has no extra meaning for it here.
    apiGet<Alert[]>(`/businesses/${businessId}/alerts`)
      .then(setAlerts)
      .catch(() => setErrors((prev) => ({ ...prev, alerts: "Could not load alerts." })));
  }, [businessId, startDate, endDate, financialCategoryId, retailCategoryId, findingsCategoryId, allBranches]);

  // Forecast is forward-looking from "today," not the start/end period
  // filter above — it depends only on the chosen horizon (plus category,
  // which only scopes the per-product table, not the horizon).
  useEffect(() => {
    if (!businessId) return;
    setErrors((prev) => ({ ...prev, forecast: undefined }));
    const categoryQs = forecastCategoryId ? `&category_id=${forecastCategoryId}` : "";
    const allBranchesQs = allBranches ? "&all_branches=true" : "";
    apiGet<Forecast>(
      `/businesses/${businessId}/analytics/forecast?horizon_days=${horizonDays}${categoryQs}${allBranchesQs}`
    )
      .then(setForecast)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, forecast: sectionErrorMessage(err, "Could not load forecast.") }))
      );
  }, [businessId, horizonDays, forecastCategoryId, allBranches]);

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
          <select
            id="business"
            value={businessId}
            onChange={(e) => setBusinessId(e.target.value)}
            disabled={allBranches}
          >
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>{" "}
          <label htmlFor="all-branches">
            <input
              id="all-branches"
              type="checkbox"
              checked={allBranches}
              onChange={(e) => setAllBranches(e.target.checked)}
            />{" "}
            Combine all branches into one view
          </label>
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

      <FinancialSection
        data={financial}
        error={errors.financial}
        categories={categories}
        categoryId={financialCategoryId}
        setCategoryId={setFinancialCategoryId}
      />
      <RetailSection
        data={retail}
        error={errors.retail}
        categories={categories}
        categoryId={retailCategoryId}
        setCategoryId={setRetailCategoryId}
      />
      <WorkshopSection data={workshop} error={errors.workshop} />
      <ForecastSection
        data={forecast}
        error={errors.forecast}
        horizonDays={horizonDays}
        setHorizonDays={setHorizonDays}
        categories={categories}
        categoryId={forecastCategoryId}
        setCategoryId={setForecastCategoryId}
      />
      <FindingsSection
        data={findings}
        error={errors.findings}
        categories={categories}
        categoryId={findingsCategoryId}
        setCategoryId={setFindingsCategoryId}
      />
      <AlertsSection alerts={alerts} error={errors.alerts} />
    </main>
  );
}

// --- Financial Performance ---------------------------------------------

function FinancialSection({
  data,
  error,
  categories,
  categoryId,
  setCategoryId,
}: {
  data: FinancialPerformance | null;
  error?: string;
  categories: ProductCategory[];
  categoryId: string;
  setCategoryId: (id: string) => void;
}) {
  const categoryFilter = <CategoryFilterSelect id="financial-category" categories={categories} categoryId={categoryId} setCategoryId={setCategoryId} />;
  if (error) return <Section title="Financial Performance">{categoryFilter}<p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Financial Performance">{categoryFilter}<p>Loading…</p></Section>;

  const { revenue, gross_margin: grossMargin } = data;
  const marginRows = dedupeByProduct([...data.bottom_margin_products, ...data.top_margin_products]);
  const grossMarginDisplayed = grossMarginDisplay(grossMargin, revenue.current);
  // grossMarginDisplay merges the net-of-tax/plain branches into one call
  // (its note text already says which one applies) — this just picks the
  // matching hover definition for whichever branch it picked.
  const grossMarginNoteTitle = grossMargin.net_gross_margin_pct !== null ? DEFINITIONS.taxCoverage : DEFINITIONS.costCoverage;

  return (
    <Section title="Financial Performance">
      {categoryFilter}
      <Stat label="Revenue" title={DEFINITIONS.revenue} value={formatMoney(revenue.current)} trendPct={revenue.change_pct} />
      {Number(data.returns.returns_amount) > 0 && (
        <p className="hint" title={DEFINITIONS.returns}>
          Includes {data.returns.return_count} return{data.returns.return_count === 1 ? "" : "s"} totaling{" "}
          {formatMoney(data.returns.returns_amount)} — already netted out of the revenue above (gross revenue
          before returns: {formatMoney(data.returns.gross_revenue)}).
        </p>
      )}
      <Stat
        label="Gross margin"
        title={DEFINITIONS.grossMargin}
        value={grossMarginDisplayed.value}
        note={grossMarginDisplayed.note}
        noteTitle={grossMarginNoteTitle}
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

function RetailSection({
  data,
  error,
  categories,
  categoryId,
  setCategoryId,
}: {
  data: RetailOperations | null;
  error?: string;
  categories: ProductCategory[];
  categoryId: string;
  setCategoryId: (id: string) => void;
}) {
  const categoryFilter = <CategoryFilterSelect id="retail-category" categories={categories} categoryId={categoryId} setCategoryId={setCategoryId} />;
  if (error) return <Section title="Retail Operations">{categoryFilter}<p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Retail Operations">{categoryFilter}<p>Loading…</p></Section>;

  const withCover = data.stock_cover.filter((r) => r.cover_days !== null);
  const noRecentSales = data.stock_cover.filter((r) => r.cover_days === null && r.stock_on_hand > 0);

  return (
    <Section title="Retail Operations">
      {categoryFilter}
      <Stat label="Inventory value" value={formatMoney(data.inventory_value.value_at_cost)} />
      <Stat label="Sell-through rate" title={DEFINITIONS.sellThrough} value={formatRate(data.sell_through_rate)} />

      <TopSellers byUnits={data.top_sellers_by_units} byRevenue={data.top_sellers_by_revenue} />

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

      <h3>Dead stock</h3>
      <p className="hint">Products with stock on hand but zero sales in the selected period — worth investigating before reordering more.</p>
      {data.dead_stock.length === 0 ? (
        <p>None — every product with stock on hand sold at least once this period.</p>
      ) : (
        <DeadStockTable rows={data.dead_stock} />
      )}
    </Section>
  );
}

// "Most sold" and "most revenue" are genuinely different questions (a
// high-price, low-volume item can dominate revenue without being what's
// actually popular) — a toggle over both, rather than one ambiguous "top
// sellers" list ranked by whichever the backend happened to pick.
function TopSellers({ byUnits, byRevenue }: { byUnits: ProductSalesRow[]; byRevenue: ProductSalesRow[] }) {
  const [sortBy, setSortBy] = useState<"units" | "revenue">("units");
  const rows = sortBy === "units" ? byUnits : byRevenue;

  return (
    <>
      <h3>
        Top sellers{" "}
        <span style={{ fontWeight: "normal", fontSize: "0.85em" }}>
          (
          <button type="button" onClick={() => setSortBy("units")} disabled={sortBy === "units"}>
            most sold
          </button>{" "}
          /{" "}
          <button type="button" onClick={() => setSortBy("revenue")} disabled={sortBy === "revenue"}>
            most revenue
          </button>
          )
        </span>
      </h3>
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
            {rows.map((row) => (
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

function CategoryFilterSelect({
  id,
  categories,
  categoryId,
  setCategoryId,
}: {
  id: string;
  categories: ProductCategory[];
  categoryId: string;
  setCategoryId: (id: string) => void;
}) {
  // Always rendered, even with zero categories — hiding it entirely made
  // the feature undiscoverable (indistinguishable from "not built") for a
  // business that hasn't imported any category data yet, found directly:
  // real feedback after it looked invisible on a business with no
  // categories.
  return (
    <div>
      <label htmlFor={id}>Category</label>{" "}
      <select id={id} value={categoryId} onChange={(e) => setCategoryId(e.target.value)} disabled={categories.length === 0}>
        <option value="">All categories</option>
        {categories.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {categories.length === 0 && (
        <span className="hint"> — no categories yet; import a file with a "category" column to use this.</span>
      )}
    </div>
  );
}

// --- Workshop Performance --------------------------------------------------

function WorkshopSection({ data, error }: { data: WorkshopPerformance | null; error?: string }) {
  if (error) return <Section title="Workshop Performance"><p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Workshop Performance"><p>Loading…</p></Section>;

  const { revenue, margin } = data;
  const workshopMargin = workshopMarginDisplay(margin);

  return (
    <Section title="Workshop Performance">
      <Stat label="Repairs completed" value={String(margin.repair_count)} />
      <Stat label="Revenue" value={formatMoney(revenue.current)} trendPct={revenue.change_pct} />
      <Stat label="Average ticket" value={margin.average_ticket !== null ? formatMoney(margin.average_ticket) : "—"} />
      <Stat
        label="Gross margin (labour only)"
        title={DEFINITIONS.workshopMargin}
        value={workshopMargin.value}
        note={workshopMargin.note}
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

// --- Forecast (Stage C13) --------------------------------------------------

const HORIZON_OPTIONS = [7, 14, 30] as const;

function ForecastSection({
  data,
  error,
  horizonDays,
  setHorizonDays,
  categories,
  categoryId,
  setCategoryId,
}: {
  data: Forecast | null;
  error?: string;
  horizonDays: number;
  setHorizonDays: (days: number) => void;
  categories: ProductCategory[];
  categoryId: string;
  setCategoryId: (id: string) => void;
}) {
  const title = (
    <>
      Forecast{" "}
      <span style={{ fontWeight: "normal", fontSize: "0.85em" }}>
        (next{" "}
        {HORIZON_OPTIONS.map((days, i) => (
          <span key={days}>
            {i > 0 && " / "}
            <button type="button" onClick={() => setHorizonDays(days)} disabled={horizonDays === days}>
              {days} days
            </button>
          </span>
        ))}
        )
      </span>
    </>
  );

  if (error) return <Section title={title}><p className="status-error">{error}</p></Section>;
  if (!data) return <Section title={title}><p>Loading…</p></Section>;

  const { result } = data.revenue;

  return (
    <Section title={title}>
      <p className="hint">
        Not AI, and not a formal statistical guarantee — a plain projection from your own sales history (either the
        average for that weekday, or a recent overall average if there isn&apos;t enough history yet to tell weekdays
        apart). The shaded range shows how much that history has typically varied, not a calculated probability.
      </p>

      <h3 title={DEFINITIONS.revenueForecast}>Revenue</h3>
      {result.insufficient_data ? (
        <p>Not enough sales history yet to forecast revenue — check back once you have at least two weeks of data.</p>
      ) : (
        <>
          <Stat
            label={`Expected revenue, next ${data.horizon_days} days`}
            title={DEFINITIONS.revenueForecast}
            value={`${formatMoney(result.total_point)} (typically ${formatMoney(result.total_low)}–${formatMoney(result.total_high)})`}
            note={`based on ${result.history_days_used} days of history — ${
              result.method === "seasonal_day_of_week"
                ? "your average for each day of the week"
                : "a plain recent daily average (not enough history yet for day-of-week patterns)"
            }`}
          />
          <Chart option={revenueForecastLineOption(result.daily)} />
        </>
      )}

      <h3 title={DEFINITIONS.reorderSuggestion}>Products to watch</h3>
      <CategoryFilterSelect id="forecast-category" categories={categories} categoryId={categoryId} setCategoryId={setCategoryId} />
      {data.products.length === 0 ? (
        <p>No products have enough sales history yet to forecast demand.</p>
      ) : (
        <>
        <p className="hint">
          &quot;Suggested reorder&quot; is a starting point only: forecast demand&apos;s upper estimate minus current
          stock. It doesn&apos;t know your supplier&apos;s delivery time or how much safety buffer you want — treat
          it as a number to sanity-check, not a purchase order.
        </p>
        <table>
          <thead>
            <tr>
              <th>Product</th>
              <th>Current stock</th>
              <th>Forecast demand</th>
              <th>Cover left</th>
              <th title={DEFINITIONS.reorderSuggestion}>Suggested reorder</th>
            </tr>
          </thead>
          <tbody>
            {data.products.map((row: ProductDemandForecast) => (
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
        </>
      )}
      {data.products_excluded_insufficient_data > 0 && (
        <p className="status-warn">
          {data.products_excluded_insufficient_data} product(s) excluded — not enough sales history yet.
        </p>
      )}
    </Section>
  );
}

// --- Findings & Recommendations -------------------------------------------

function FindingsSection({
  data,
  error,
  categories,
  categoryId,
  setCategoryId,
}: {
  data: Findings | null;
  error?: string;
  categories: ProductCategory[];
  categoryId: string;
  setCategoryId: (id: string) => void;
}) {
  if (error) return <Section title="Findings & Recommendations"><p className="status-error">{error}</p></Section>;
  if (!data) return <Section title="Findings & Recommendations"><p>Loading…</p></Section>;
  if (data.recommendations.length === 0) {
    return (
      <Section title="Findings & Recommendations">
        <p>Nothing to flag for this period.</p>
      </Section>
    );
  }

  const findingByKey = buildFindingByKey(data.findings);
  const { businessWide, stockAndProducts } = splitRecommendations(data.recommendations);

  return (
    <Section title="Findings & Recommendations">
      {businessWide.length > 0 && (
        <>
          <h3>Business performance</h3>
          <RecommendationList recommendations={businessWide} findingByKey={findingByKey} showCategory={false} />
        </>
      )}

      <h3>Stock &amp; products</h3>
      <CategoryFilterSelect id="findings-category" categories={categories} categoryId={categoryId} setCategoryId={setCategoryId} />
      {stockAndProducts.length === 0 ? (
        <p>Nothing to flag for this period.</p>
      ) : (
        <RecommendationList recommendations={stockAndProducts} findingByKey={findingByKey} showCategory={true} />
      )}
    </Section>
  );
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

// --- Page-local helpers ------------------------------------------------

function periodQuery(start: string, end: string, categoryId?: string, allBranches?: boolean): string {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (categoryId) params.set("category_id", categoryId);
  if (allBranches) params.set("all_branches", "true");
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

// The backend's own detail message matters here more than usual — a 409
// ("these branches don't share one timezone") or 403 ("not a member of
// every business in this group") is specific and actionable, not just
// "something failed," so it's surfaced directly rather than replaced with
// the generic per-section fallback.
function sectionErrorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function dedupeByProduct(rows: ProductMarginRow[]): ProductMarginRow[] {
  const byId = new Map(rows.map((r) => [r.product_id, r]));
  return Array.from(byId.values());
}
