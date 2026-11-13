# ADR-027: Calculation integrity rules found in the 12/11/2026 end-to-end walkthrough

**Status:** Accepted (implemented)
**Date:** 2026-11-12
**Related:** ED-007, ED-010, `backend/app/imports/importer.py`, `backend/app/analytics/forecasting.py`, `backend/app/application/forecast.py`, `backend/app/analytics/findings.py`, `backend/app/analytics/financial.py`, `backend/app/invoices/extraction.py`

## Context

A full local walkthrough with a synthetic bike-shop dataset (2,176 sales lines, 66 purchases, 188 repairs, a stock count, a PDF invoice) and an independent recomputation of every figure exposed rules that were either wrong or undefined. All figures now match the independent recomputation (80/80 checks).

## Decision

1. **Sale-line cost snapshot.** When a sales file has no cost column (the norm for POS exports), each line's `cost_price_at_sale` is the product's known cost from earlier stock-count/purchase imports. A file-supplied cost always wins; a product first seen in the sales file stays unknown. *(Before: every line was NULL, so margin showed 0% coverage.)*
2. **VAT conventions.** A sales line is a "total mismatch" only if its total matches neither `price × qty` (VAT-inclusive price, normal in Ireland/EU) nor `price × qty + VAT` (VAT-exclusive). The file's total is always the revenue figure.
3. **Negative derived stock** means the stock count is stale, not a real shortfall. For suggested reorder quantities it counts as zero on hand (`max(0, ceil(forecast_high) − max(stock, 0))`), and a `negative_stock` data-quality finding asks for a fresh stock count. *(Supersedes the earlier rule that added the deficit to the order: −499 became a 533-unit order.)*
4. **Forecast floor.** Forecast demand is never negative, even when returns outnumber sales in the history.
5. **Margin ranking exclusions.** Only a product that actually sold without a known cost counts as "excluded — no recorded cost price"; returns-only products are left out of ranking silently.
6. **Purchases cost warning** fires only when the same product is bought at different unit costs in one file.
7. **PDF invoices.** A VAT/tax *registration number* is never read as the tax total; supplier names also match ignoring company suffixes ("Ltd", "Limited", "PLC"…) when exactly one supplier shares the base name.
8. **Timezones** must be valid IANA names (period calculations depend on them).

## Consequences

Margins, findings (loss-making products) and ORLA answers now work for typical POS exports. Historical margins use the latest known product cost, which is an approximation when costs changed over time; a cost column in the sales file removes it.

## Alternatives Considered

- Leaving cost unknown unless the sales file has it: mathematically purest, but makes margin unusable for most shops.
- Treating negative stock as a real deficit: produced absurd orders and hid the real problem (stale counts).

## Review Trigger

Pilot data showing frequent cost changes (consider cost-at-date from purchase history) or POS exports with stock that legitimately goes negative (e.g. pre-orders).
