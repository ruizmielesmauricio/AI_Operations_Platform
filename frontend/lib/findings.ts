import type { Finding, Recommendation } from "@/types";

// Whole-business rules — never scoped by category, and deliberately
// shown separately from the per-product ones on both the dashboard and
// reports pages: a revenue-decline finding is a business-wide trend, not
// something related to any one stock category. Kept in sync with
// backend/app/analytics/findings.py::evaluate_all's own four
// whole-business rules (the other three — low_stock/dead_stock/
// product_selling_at_loss — are per-product and belong in the
// filterable/stock group instead).
export const BUSINESS_WIDE_FINDING_TYPES = new Set([
  "revenue_decline",
  "low_gross_margin",
  "incomplete_cost_data",
  "high_return_rate",
]);

export function splitRecommendations(recommendations: Recommendation[]): {
  businessWide: Recommendation[];
  stockAndProducts: Recommendation[];
} {
  return {
    businessWide: recommendations.filter((r) => BUSINESS_WIDE_FINDING_TYPES.has(r.finding_type)),
    stockAndProducts: recommendations.filter((r) => !BUSINESS_WIDE_FINDING_TYPES.has(r.finding_type)),
  };
}

// Recommendation.evidence is the same dict as its source Finding.evidence
// (assigned directly on the backend), so matching on finding_type plus
// the per-product evidence key (when present) reliably pairs a
// recommendation back to the finding it explains (whose .message names
// the specific product) — the two lists are sorted differently
// (recommendations by severity/impact, findings by evaluation order), so
// a positional zip would pair them incorrectly.
export function findingKey(type: string, evidence: Record<string, unknown>): string {
  return `${type}:${evidence.product_id ?? ""}`;
}

export function buildFindingByKey(findings: Finding[]): Map<string, Finding> {
  return new Map(findings.map((f) => [findingKey(f.type, f.evidence), f]));
}
