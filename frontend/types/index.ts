export interface Business {
  id: string;
  name: string;
  template: string;
  timezone: string;
  role: string;
}

export interface SubscriptionStatus {
  status: string | null;
  current_period_end: string | null;
}

export interface RejectionReason {
  count: number;
  message: string;
  sample_rows: Record<string, unknown>[];
}

export interface RejectionSummary {
  reasons?: Record<string, RejectionReason>;
  warnings?: Record<string, RejectionReason>;
}

export interface ImportRecordSummary {
  id: string;
  status: string;
  rows_total: number;
  rows_imported: number;
  rows_rejected: number;
  rejection_summary: RejectionSummary | null;
  reversed_at: string | null;
}

export interface Upload {
  id: string;
  original_filename: string;
  entity_type: string;
  status: string;
  created_at: string;
  import_record: ImportRecordSummary | null;
}

export interface UploadFreshnessEntry {
  entity_type: string;
  last_completed_at: string | null;
}

export interface ImportRunResponse {
  import_record_id: string;
  status: string;
  rows_total: number;
  rows_imported: number;
  rows_rejected: number;
  rejection_summary: RejectionSummary | null;
}

export interface ImportUndoResponse {
  import_record_id: string;
  status: string;
  reversed_at: string | null;
}

export interface FieldCandidate {
  source_column: string;
  confidence: number;
  source: "alias" | "structural" | "ai";
  sample_values: string[];
}

export interface DetectMappingResponse {
  status: "reused" | "needs_confirmation" | "header_not_found";
  mapping_profile_id: string | null;
  suggested_mapping: Record<string, string | null>;
  columns: string[];
  field_candidates: Record<string, FieldCandidate[]>;
  unmapped_columns: string[];
  preview_rows: string[][] | null;
}

export interface ConfirmMappingResponse {
  import_record_id: string;
  mapping_profile_id: string;
  status: string;
}

// --- Stage C9/C10/C11/C12: analytics dashboard -----------------------------
//
// Decimal fields on the backend (app/schemas/analytics.py) serialize as JSON
// strings, not numbers (pydantic's default for `Decimal`, e.g.
// `"gross_margin_pct": "50.0"`) — kept as `string` here too, all the way
// until a chart needs a `number`, so nothing silently loses precision by
// round-tripping through a JS float in application state.

export interface Period {
  start: string;
  end: string;
}

// --- Product categories (dashboard filters + reports breakdown table) --

export interface ProductCategory {
  id: string;
  name: string;
}

export interface CategoryBreakdownRow {
  category_id: string | null;
  // "Uncategorized" for the synthetic no-category bucket.
  category_name: string;
  revenue: string;
  // Purchase cost (unit cost x qty received) — NOT cost of goods sold, a
  // different, already-existing figure this deliberately doesn't reuse.
  expenses: string;
  // Null when this category had zero purchase quantity in the period at
  // all; otherwise the % of that quantity whose cost is actually known
  // (most purchases before this feature shipped have no per-purchase
  // cost captured — see backend InventoryMovement.unit_cost).
  expenses_data_coverage_pct: string | null;
  // Current stock on hand x SELL price — deliberately different from
  // Retail Operations' inventory_value stat, which stays at cost.
  stock_value: string;
  products_excluded_from_stock_value: number;
}

export interface CategoryBreakdown {
  period: Period;
  rows: CategoryBreakdownRow[];
}

export interface Revenue {
  current: string;
  previous: string;
  change_pct: string | null;
}

export interface GrossMargin {
  total_revenue: string;
  revenue_with_known_cost: string;
  cogs: string;
  gross_profit: string;
  gross_margin_pct: string | null;
  cost_data_coverage_pct: string | null;
  // Margin computed net of tax, over only sales with both a known cost and
  // a known tax_amount — None until at least one line has both. Prefer
  // this over gross_margin_pct whenever it's set: gross_margin_pct may
  // overstate margin for any revenue sourced from a tax-inclusive total.
  net_gross_profit: string | null;
  net_gross_margin_pct: string | null;
  tax_data_coverage_pct: string | null;
}

export interface ProductMarginRow {
  product_id: string;
  name: string;
  revenue: string;
  gross_profit: string;
  gross_margin_pct: string;
  // Null when the product has no category set (the overwhelming majority
  // until categories are actively imported via an upload's optional
  // "category" column).
  category_name: string | null;
}

export interface Returns {
  gross_revenue: string;
  returns_amount: string;
  return_count: number;
  // Always equal to revenue.current above — this just decomposes it
  // explicitly (gross minus returns) rather than leaving returns
  // silently netted in with no visibility.
  net_revenue: string;
  return_rate_pct: string | null;
}

export interface FinancialPerformance {
  period: Period;
  revenue: Revenue;
  gross_margin: GrossMargin;
  top_margin_products: ProductMarginRow[];
  bottom_margin_products: ProductMarginRow[];
  products_excluded_from_ranking: number;
  returns: Returns;
}

export interface ProductSalesRow {
  product_id: string;
  name: string;
  units_sold: number;
  revenue: string;
  category_name: string | null;
}

export interface StockCoverRow {
  product_id: string;
  name: string;
  stock_on_hand: number;
  units_sold_in_period: number;
  cover_days: string | null;
  revenue_in_period: string;
  category_name: string | null;
}

export interface DeadStockRow {
  product_id: string;
  name: string;
  stock_on_hand: number;
  value_at_cost: string | null;
  category_name: string | null;
}

export interface InventoryValue {
  value_at_cost: string;
  products_missing_cost: number;
}

export interface RetailOperations {
  period: Period;
  top_sellers_by_units: ProductSalesRow[];
  top_sellers_by_revenue: ProductSalesRow[];
  stock_cover: StockCoverRow[];
  dead_stock: DeadStockRow[];
  inventory_value: InventoryValue;
  sell_through_rate: string | null;
}

export interface WorkshopMargin {
  repair_count: number;
  revenue: string;
  revenue_coverage_pct: string | null;
  labour_cost: string;
  gross_profit: string;
  gross_margin_pct: string | null;
  labour_cost_coverage_pct: string | null;
  average_ticket: string | null;
}

export interface WorkshopPerformance {
  period: Period;
  revenue: Revenue;
  margin: WorkshopMargin;
}

export type FindingSeverity = "critical" | "warning" | "info";

export interface Finding {
  type: string;
  severity: FindingSeverity;
  message: string;
  evidence: Record<string, unknown>;
  rule_id: string;
  rule_version: number;
}

export interface Recommendation {
  finding_type: string;
  severity: FindingSeverity;
  title: string;
  description: string;
  evidence: Record<string, unknown>;
  impact_score: string;
}

export interface Findings {
  period: Period;
  findings: Finding[];
  recommendations: Recommendation[];
}

export interface Alert {
  id: string;
  alert_type: string;
  product_id: string | null;
  payload: {
    severity: FindingSeverity;
    message: string;
    evidence: Record<string, unknown>;
  };
  status: string;
  created_at: string;
  updated_at: string;
}

// --- Stage C13 — Forecasting -----------------------------------------

export interface DailyForecast {
  forecast_date: string;
  point: string;
  low: string;
  high: string;
}

export interface ForecastResult {
  // True when there's under the backend's minimum lookback history —
  // every field below is then meaningless and must not be displayed.
  insufficient_data: boolean;
  method: "seasonal_day_of_week" | "moving_average" | null;
  history_days_used: number;
  daily: DailyForecast[];
  total_point: string;
  total_low: string;
  total_high: string;
}

export interface RevenueForecast {
  horizon_days: number;
  result: ForecastResult;
}

export interface ProductDemandForecast {
  product_id: string;
  name: string;
  sku: string | null;
  result: ForecastResult;
  current_stock: number;
  // A simple starting suggestion (confidence band's high end minus
  // current stock) — does not model supplier lead time or safety stock.
  suggested_reorder_quantity: number;
  days_of_cover_at_forecast_rate: string | null;
  category_name: string | null;
}

export interface Forecast {
  horizon_days: number;
  revenue: RevenueForecast;
  products: ProductDemandForecast[];
  products_excluded_insufficient_data: number;
}

// --- Stage D17/D18 — scheduled weekly/monthly reports -----------------
//
// The report payload (app/application/report.py::_assemble_payload)
// reuses the exact same dashboard Pydantic schemas to serialize each
// section, so it's reusing the exact same TypeScript shapes here too —
// a report and the live dashboard can never disagree about a number's
// shape.

export interface ReportSummary {
  id: string;
  report_type: "weekly" | "monthly";
  period_start: string;
  period_end: string;
  status: string;
  created_at: string;
  expires_at: string | null;
}

export interface ReportExecutiveSummary {
  narrative: string[];
  transactions: number;
  average_sale: string | null;
  low_stock_count: number;
  dead_stock_count: number;
  top_recommendations: Recommendation[];
}

export interface ReportInventoryHealth {
  fast_movers: StockCoverRow[];
  slow_movers: StockCoverRow[];
  // A simplification, stated on the page: current inventory value, not a
  // true period-average — see app/analytics/retail.py::compute_inventory_turnover.
  turnover_ratio: string | null;
}

export interface ReportPayload {
  business_name: string;
  business_type: string;
  report_type: "weekly" | "monthly";
  period_start: string;
  period_end: string;
  generated_at: string;
  executive_summary: ReportExecutiveSummary;
  financial_performance: FinancialPerformance;
  retail_operations: RetailOperations;
  inventory_health: ReportInventoryHealth;
  forecast: Forecast;
  findings: Findings;
  // Omitted (null), not faked, for any business whose template isn't
  // "bicycle_shop" (PR-8.3's "sections omitted, not faked when
  // inapplicable").
  workshop_performance: WorkshopPerformance | null;
  // Never filtered (unlike the dashboard's per-section category
  // dropdowns) — a report always shows every category.
  category_breakdown: CategoryBreakdown;
}

export interface ReportDetail extends ReportSummary {
  payload: ReportPayload | null;
}

// --- Stage E19-E24 — AI business Q&A chat -------------------------------

export interface ChatResponse {
  answer: string;
  intent: string;
  // False when the AI's raw answer failed the PR-5.3 grounding guardrail
  // and `answer` is a safe fallback message instead.
  grounded: boolean;
  // A fixed, small set of app pages ("dashboard" | "reports") the answer
  // references. Rendered as real <a> elements by the chat page itself —
  // never by treating any part of `answer` (which may include
  // model-generated text) as HTML.
  links: string[];
}
