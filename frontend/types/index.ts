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
}

export interface FinancialPerformance {
  period: Period;
  revenue: Revenue;
  gross_margin: GrossMargin;
  top_margin_products: ProductMarginRow[];
  bottom_margin_products: ProductMarginRow[];
  products_excluded_from_ranking: number;
}

export interface ProductSalesRow {
  product_id: string;
  name: string;
  units_sold: number;
  revenue: string;
}

export interface StockCoverRow {
  product_id: string;
  name: string;
  stock_on_hand: number;
  units_sold_in_period: number;
  cover_days: string | null;
  revenue_in_period: string;
}

export interface DeadStockRow {
  product_id: string;
  name: string;
  stock_on_hand: number;
  value_at_cost: string | null;
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
}

export interface Forecast {
  horizon_days: number;
  revenue: RevenueForecast;
  products: ProductDemandForecast[];
  products_excluded_insufficient_data: number;
}
