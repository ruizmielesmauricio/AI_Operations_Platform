// Shared formatting helpers for Decimal-as-string fields coming back from
// the backend (app/schemas/analytics.py serializes Decimal to JSON string,
// never a float — see types/index.ts's note). Extracted from
// frontend/app/dashboard/page.tsx so frontend/app/reports/[id]/page.tsx can
// render the same numbers identically, not via a second hand-rolled copy.

import type { GrossMargin, WorkshopMargin } from "@/types";

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

// A day-count Decimal like "7.00" or "7.0" reads worse than a plain "7"
// when it's a whole number — strips trailing zeros/decimal point without
// rounding a genuine fractional value (e.g. "7.5" stays "7.5"). Used by
// the Product Reorder Rules table (reorder point / ORLA recommends),
// never by anything money-related — formatMoney above is untouched and
// always keeps its 2 decimal places, which is a different, deliberate
// convention for currency.
export function formatDays(value: string): string {
  // Number("7.00") === 7, and String(7) === "7" — converting through
  // Number and back to String is enough to drop trailing zeros for a
  // whole number while leaving a genuine fraction like "7.5" alone.
  return String(Number(value));
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

// Same "prefer net-of-tax whenever it's known" precedent as
// grossMarginDisplay above, applied to Workshop Performance's labour-only
// margin — price_charged on a workshop invoice is very often a
// tax-inclusive total, the exact same shape that made sales' margin
// overstate itself before that fix (v1.13).
export function workshopMarginDisplay(margin: WorkshopMargin): { value: string; note: string } {
  if (margin.net_gross_margin_pct !== null && margin.net_gross_profit !== null) {
    return {
      value: formatPct(margin.net_gross_margin_pct),
      note: `${formatMoney(margin.net_gross_profit)} kept as gross profit (net of tax, labour only — parts cost not tracked yet) — based on ${formatPct(margin.tax_data_coverage_pct)} of labour-cost-known revenue with confirmed tax figures`,
    };
  }
  return {
    value: formatPct(margin.gross_margin_pct),
    note:
      margin.labour_cost_coverage_pct !== null
        ? `based on ${formatPct(margin.labour_cost_coverage_pct)} of revenue with known labour cost — parts cost not tracked yet (may include tax if your prices/totals are tax-inclusive)`
        : "no labour cost recorded yet",
  };
}
