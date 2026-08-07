// Shared formatting helpers for Decimal-as-string fields coming back from
// the backend (app/schemas/analytics.py serializes Decimal to JSON string,
// never a float — see types/index.ts's note). Extracted from
// frontend/app/dashboard/page.tsx so frontend/app/reports/[id]/page.tsx can
// render the same numbers identically, not via a second hand-rolled copy.

import type { GrossMargin } from "@/types";

export function formatMoney(value: string): string {
  const n = Number(value);
  return `€${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPct(value: string | null): string {
  return value !== null ? `${value}%` : "—";
}

export function formatRate(value: string | null): string {
  return value !== null ? `${(Number(value) * 100).toFixed(1)}%` : "—";
}

export function severityClass(severity: string): string {
  if (severity === "critical") return "status-error";
  if (severity === "warning") return "status-warn";
  return "status-info";
}

// "Gross margin: 39.9%" alone doesn't say what that means in practice —
// this always pairs the percentage with the actual cash figure (what's
// left after paying for the stock sold, out of total revenue), so a
// reader doesn't have to do the arithmetic themselves. Prefers the
// net-of-tax figures whenever any tax data is known, same precedent as
// frontend/app/dashboard/page.tsx's original branching — gross_margin_pct
// alone may overstate margin for revenue sourced from a tax-inclusive
// total.
export function grossMarginDisplay(gm: GrossMargin, revenueCurrent: string): { value: string; note: string } {
  if (gm.net_gross_margin_pct !== null && gm.net_gross_profit !== null) {
    return {
      value: formatPct(gm.net_gross_margin_pct),
      note: `${formatMoney(gm.net_gross_profit)} kept as gross profit (net of tax) after the cost of goods sold, out of ${formatMoney(revenueCurrent)} total revenue — based on ${formatPct(gm.tax_data_coverage_pct)} of cost-known revenue with confirmed tax figures`,
    };
  }
  return {
    value: formatPct(gm.gross_margin_pct),
    note:
      gm.cost_data_coverage_pct !== null
        ? `${formatMoney(gm.gross_profit)} kept as gross profit after the cost of goods sold, out of ${formatMoney(revenueCurrent)} total revenue — based on ${formatPct(gm.cost_data_coverage_pct)} of revenue with known cost (may include tax if your prices/totals are tax-inclusive)`
        : "no cost data recorded yet",
  };
}
