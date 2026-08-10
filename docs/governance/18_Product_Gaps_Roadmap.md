# 18_Product_Gaps_Roadmap.md

**Version:** 1.1
**Status:** Draft
**Phase:** Phase 3 (Core Product) / Phase 7 (Expansion), see per-gap classification below
**Author:** Founder & CTO
**Last Updated:** 10/08/2026

---

**Update, 10/08/2026 (v1.56):** Gaps 1, 4, and 5 below are now implemented — see `11_Development_Roadmap.md`'s v1.56 entry for the full change list. This document's per-gap build plans are kept as-written below (the actual build matched them closely) rather than rewritten after the fact, so they remain an accurate record of what was scoped before building. Two sub-pieces were explicitly deferred within the "implemented" gaps, per their own stated escape hatches: Gap 1's automatic scheduled threshold-recompute job (the calculation surface is built and callable; no new recurring job applies it automatically yet), and a dedicated AI "explain this recommendation" round-trip (judged unnecessary — the recommendation's `basis`/`lead_time_days`/`safety_buffer_days` fields are already self-explanatory without an AI call). Gap 2 was fixed in v1.55; Gap 3 remains explicitly out of scope, unchanged.

---

# Document Contract

## Purpose

This document is the detailed build-plan for a specific set of product gaps identified during a real logged-in session walkthrough (10/08/2026): each surface a live pilot would actually touch, but that was either partially built, deliberately deferred, or explicitly out of scope at the time it was flagged. Unlike `11_Development_Roadmap.md` (phase-level gates and a running changelog), this document works at feature-detail level — for each gap it specifies the UI, states, CRUD/security/audit/test requirements, and data-model implications needed to build it to the same standard as everything already shipped.

## Audience

* Founder
* Engineering Team
* Future Employees

## In Scope

* Detailed build plans for the five gaps below
* An explicit in-scope-now / roadmap-future / out-of-scope classification per gap

## Out of Scope

* Phase-level sequencing (see `11_Development_Roadmap.md`)
* Requirements not yet raised as a concrete gap

## Related Documents

* `10_Product_Requirements.md` (PR-9 Alerts, PR-2 Data Ingestion)
* `11_Development_Roadmap.md` (v1.54 changelog entry closes Gap 2)
* `00_Company_Constitution.md` ("Business Logic First" — binds every AI-adjacent item below)

---

# Gap 1 — Low-Stock Alert Thresholds And ORLA Recommendations

**Classification: Roadmap / future work.**

## Current state

Per-product/per-category low-stock thresholds already exist in the database (`app/models/product.py` / `app/models/product_category.py`, wired into `app/analytics/alerts.py`'s `evaluate_low_stock`, PR-9). There is no UI anywhere to set them — they're either unset (falling back to a default) or would need to be written directly against the database.

## Desired direction

Two layers, kept strictly separate per `CLAUDE.md`'s Core Rule:

1. **Deterministic backend**: compute per-product sales velocity (units/day over a trailing window, reusing the same lookback logic `app/analytics/forecast.py` already has), stock cover (already computed in `app/analytics/retail.py`), and a lead-time estimate (see Gap 4 — genuinely unknown until supplier data exists, so defaults to a configurable business-level constant until then). From these, compute a `recommended_minimum_stock` figure, deterministically, in `app/analytics/alerts.py` or a new `app/analytics/replenishment.py`.
2. **ORLA (AI)**: explains and recommends *based on* the computed figure above — "Product X sells about 3/day; at your current 40-day lead-time buffer that's a recommended minimum of 90 units." ORLA never invents or recalculates the number itself; the recommendation UI passes the deterministic figure into the AI explain-context the same way `app/ai/service.py` already does for existing dashboard figures.

## Build requirements

- **UI links/buttons/actions**: a new "Thresholds" tab/section on the product list (dashboard or a new `/products` management page — none exists today; the product catalogue is currently only visible indirectly through sales/inventory rows). Per product/category: an editable minimum-stock field, a "Use recommended" button that fills it from the deterministic recommendation, and a manual override that persists independently of any future recalculation.
- **Empty/loading/error/success states**: empty state before ~4–6 weeks of sales history ("Not enough data yet — recommendations activate once there's more sales history"), loading skeleton while the recommendation computes, inline error if the analytics call fails, a success toast/inline confirmation on save.
- **CRUD/activate-deactivate**: create (set a threshold where none exists), read (list all products with their current threshold + recommended value side by side), update (edit or accept a recommendation), no delete — clearing back to "no threshold set" is the equivalent of removing an override.
- **Automatic product-specific thresholds after enough data exists**: a scheduled job (reusing the existing `scheduler` service's tick pattern, `app/scheduler/tick.py`) that recomputes recommendations weekly and flags (not silently overwrites) products whose recommendation has drifted significantly from the current setting, surfaced as a dashboard notice rather than an automatic change — a manual override must never be silently clobbered.
- **Manual override support**: as above — an explicit `is_manual_override: bool` column (or a nullable `override_set_at` timestamp) on the threshold row, so the recompute job knows not to touch it.
- **Per-branch threshold handling**: thresholds are per-`Product`, and `Product` is already tenant-scoped by `business_id` — a branch (its own `Business` row per the existing parent/child model) has its own separate `Product` catalogue, so this falls out for free with no special-casing, consistent with every other per-product feature in this codebase.
- **Security/authorization**: owner/manager only (matches every other business-configuration surface — staff can view, not edit, mirroring the existing `Membership.role` gate pattern already used on `PATCH /businesses/{id}` and employee-seat management routes).
- **Tenant and branch isolation**: standard `business_id` scoping on every read/write, tenant-isolation tests following this codebase's existing per-feature convention (e.g. `tests/tenant_isolation/test_purchases_repairs_isolation.py`).
- **Audit logging**: `threshold_updated` (manual edit), `threshold_recommendation_accepted` (one-click accept), via the existing `record_audit_event` (PR-6.5) — no new audit infrastructure needed.
- **Tests needed**: unit tests for the velocity/lead-time/recommended-minimum formula (pure function, `tests/unit/`), integration tests for the threshold CRUD routes, tenant isolation tests, and a regression test proving a manual override survives a scheduled recompute.
- **Data model/API implications**: no new table required if thresholds stay on `Product`/`ProductCategory` directly (already the case); a new `GET/PATCH /businesses/{id}/products/{id}/threshold` route pair, plus a `GET .../products/{id}/threshold-recommendation` read-only endpoint for the deterministic figure ORLA and the UI both consume.

---

# Gap 2 — Repair Margin Tax-Inclusive Bug

**Classification: Fixed — closed this round (v1.54, 09/08/2026).**

`price_charged` on a workshop repair is very often a tax-inclusive total, the same shape that overstated sales margin before v1.13's fix. `app/analytics/workshop.py::compute_workshop_margin` now computes `net_gross_profit`/`net_gross_margin_pct`/`tax_data_coverage_pct` over only repairs where labour cost *and* tax are both known — the same principle as `app/analytics/financial.py`'s `net_gross_margin_pct`, never blending a tax-unknown repair into a "confirmed net" figure. A new optional `tax_amount` field was added to the repairs upload (mirrors sales' `tax_amount` exactly — `ProductionEvent.tax_amount`, migration `a7d2e9c14f5b`). Dashboard and Reports both now show the net-of-tax figure whenever any tax data exists, with the same honest fallback wording as the sales side. See `11_Development_Roadmap.md`'s v1.54 entry for the full change list and test count.

---

# Gap 3 — Real-Time Repair Logging Screen

**Classification: Explicitly out of scope — future idea only, not built.**

Repairs are ingested exclusively via the periodic "repairs" upload entity type (a shop's own workshop-log export). There is no live "log a repair as it happens" data-entry screen, and per direct product-direction confirmation this is **not** being built now — the platform is not currently offering a real-time event-tracking service, only upload/import-based analytics.

Recorded here only as a future idea, not scoped or designed: if the product later expands beyond upload/import-based analytics, a real-time repair/event entry screen could write directly into `ProductionEvent`/`ProductionEventInput` (the input/parts-consumed side is already schema-only, unconsumed by any writer today — see `app/models/production_event.py`'s own docstring) rather than through the batch importer. No further design work has been done on this; it is not sized, scheduled, or estimated.

---

# Gap 4 — Supplier Tracking On Purchases

**Classification: Roadmap / future work.**

## Current state

`purchases` uploads capture product, quantity, unit cost, and an optional reference — no concept of *who the stock was bought from* exists anywhere in the schema.

## Build requirements

- **Data model**: new `suppliers` table (tenant-scoped via `business_id`, per every other table in this schema — `id`, `name`, `normalized_name` for match-or-create, optional contact fields, `created_at`/`updated_at`), plus a `product_id ↔ supplier_id` link. Two shapes are plausible: (a) a nullable `preferred_supplier_id` directly on `Product` (simplest, matches "current cost price" being a single mutable field on `Product` already), or (b) a `product_suppliers` join table if a product can genuinely have more than one supplier with different lead times — needs a direct product decision before building, not assumed here. `inventory_movements` (reason="purchase") gains a nullable `supplier_id`, mirroring how `unit_cost` was added there (migration `d3f8a1c9e6b2`) — a per-transaction snapshot, not just a product-level default, since the same product can legitimately be sourced from different suppliers over time.
- **Ingestion**: a new optional `supplier` canonical field on the `purchases` upload entity type only (mirrors `category`'s exact match-or-create pattern in `app/imports/aliases.py`/`app/imports/importer.py`'s `_CategoryMatcher` — a `_SupplierMatcher` doing the same normalized-name lookup). Never required — `MINIMUM_MAPPING_RULES["purchases"]` stays unchanged.
- **Automatically create/match suppliers**: match-or-create by normalized name on every purchase row that maps a supplier column, exact same mechanism as category resolution.
- **Allow duplicate supplier merging**: a merge action (owner-only) that repoints every `inventory_movements.supplier_id`/`Product.preferred_supplier_id` reference from a duplicate supplier row to the canonical one, then soft-deletes (not hard-deletes, consistent with `soft_delete_business`'s precedent) the duplicate. Needs its own confirmation UI showing exactly how many purchase rows will be repointed before committing.
- **Allow manual correction**: an edit action on a purchase row (or on the supplier record itself) to fix a mis-matched supplier after the fact — no such per-row edit UI exists for purchases today, so this is new surface, not an extension of an existing one.
- **Allow Unknown supplier rather than making it mandatory**: `supplier_id` stays nullable everywhere; a purchase with no mapped supplier column, or an unmatched name, is fine, not a rejection.
- **UI links/buttons/actions**: new Suppliers list/detail page (name, linked products, purchase history, basic totals); Create/Edit/Deactivate actions (soft-delete, not hard-delete, matching this app's established convention); a "Merge duplicates" flow reachable from the list; a manual "change supplier" action on the purchase-history view (which doesn't exist as a browsable list today either — see Gap 5, these two are complementary).
- **Empty/loading/error/success states**: empty state on the Suppliers list before any purchase has ever mapped one ("No suppliers yet — map a Supplier column on your next purchases upload, or add one manually"), standard loading/error/success elsewhere.
- **Basic supplier analytics**: total spend per supplier over a period, reusing the exact aggregation pattern `app/analytics/category.py` already established for category breakdown (same shape, different grouping key) — not a new analytics primitive.
- **Integration with low-stock recommendations and lead-time calculations**: once `Product.preferred_supplier_id` (or equivalent) exists, Gap 1's `recommended_minimum_stock` formula can read a real per-supplier lead time instead of the business-level default constant it starts with — explicitly sequenced as a Gap 1 follow-up, not built until Gap 1's own foundation exists.
- **Security/authorization**: owner/manager can create/edit/merge/deactivate; staff read-only, same role pattern as every other business-configuration surface in this app.
- **Tenant/branch isolation**: standard `business_id` scoping; tenant isolation tests following the existing per-feature convention.
- **Audit logging**: `supplier_created`, `supplier_merged` (record both the surviving and the merged-away id), `supplier_deactivated`, `purchase_supplier_corrected`.
- **Tests needed**: unit tests for the match-or-create normalization logic (mirrors existing `_CategoryMatcher` tests), integration tests for merge (repointing verified, not just the duplicate's own row), tenant isolation tests, and a regression test proving a mapped-but-unmatched supplier name never blocks the rest of the purchase row from importing.

---

# Gap 5 — Dashboard Drill-Down To Raw Transactions

**Classification: Roadmap / future work.**

## Current state

Dashboard/Reports drill-down stops at aggregated per-product or per-repair breakdown rows (Stage C11's stated, deliberate scope limit — see `11_Development_Roadmap.md`'s C11 entry: "full raw-record drill-down flagged as a follow-up, no endpoint lists individual sales rows yet"). No endpoint returns individual `Sale`/`SaleItem`/purchase/repair rows.

## Build requirements

- **UI links/buttons/actions**: clickable dashboard metric tiles/chart bars (e.g. a product's row in Top Sellers, a category's bar in the category breakdown) linking through to a new transaction-list view scoped to that click's filters (product/category/date range/branch already carried, matching the existing dashboard filter state).
- **Transaction table UI**: paginated table of individual `Sale`/`SaleItem` (or purchase/repair) rows for the selected scope — date, product, quantity, unit price, total, source-upload reference.
- **Filter controls**: date range, category, product, and branch/all-branches — all four already exist as dashboard-level filter state (per PR-3/the branch-filter feature, `app/application/business_group.py`) and should be carried into this view rather than reset, not re-invented.
- **Detail drawer/page**: a single transaction's full detail (every field on the row, plus which upload/import created it) — mostly useful for tracing a data-quality question back to its source file.
- **Source-upload reference**: every `Sale`/`ProductionEvent`/purchase-originating `InventoryMovement` row already carries `import_record_id` — surfacing it as a link back to that upload's detail page (`app/api/uploads.py`, already has an upload-detail route) is additive, not a new relationship.
- **Empty/loading/error/success states**: empty state when a filter combination matches nothing, loading skeleton for the (potentially large) query, error state on a failed fetch, standard pagination controls (no "success" state as such beyond the populated table).
- **Pagination and performance considerations**: this is the one gap in this document with a real scale risk — a business with tens of thousands of sale rows must not have this endpoint do an unbounded `SELECT *`. Cursor or offset pagination (matching whichever pattern this codebase's other list endpoints already use — currently all bounded/capped, e.g. `find_repairs`'s `limit`), with a sensible default page size and an explicit hard cap.
- **PII minimization**: sales/repairs deliberately capture no customer name/email (`Sale.customer_id`/`ProductionEvent.customer_id` are optional FKs, essentially unused today — see `app/models/production_event.py`'s own docstring). This drill-down must not become the first feature to expose customer-identifying detail that the rest of the app has deliberately never surfaced — no new customer-identifying columns should be added to satisfy this feature.
- **Security/authorization**: same `get_current_membership` gate as the rest of Dashboard/Reports/Uploads — any role can view (matches today's "any authenticated member sees the shop's own data" posture), no new restriction needed since this is strictly a more granular view of data the role can already see aggregated.
- **Tenant/branch isolation**: standard `business_id` scoping (and the `all_branches` group-resolution path from the branch-filter feature, `app/application/business_group.py::get_business_group`, if a business group view is requested); tenant isolation tests following this codebase's existing per-feature convention.
- **Audit logging**: none needed — this is a read-only view of data the role can already see in aggregate; no new mutation is introduced.
- **Tests needed**: integration tests for the new list route (filter combinations, pagination boundaries), a tenant-isolation test proving business A cannot page through business B's transactions even with a guessed offset/cursor, and a performance-oriented test asserting the hard page-size cap is actually enforced server-side (not just a frontend default that a direct API call could bypass).
- **Data model/API implications**: no schema changes — every field this needs already exists on `Sale`/`SaleItem`/`InventoryMovement`/`ProductionEvent`. New read-only routes only: `GET /businesses/{id}/sales`, `GET /businesses/{id}/purchases`, `GET /businesses/{id}/repairs` (or repairs may already be adequately served by the existing `find_repairs` repository method with its `limit` widened into real pagination — worth checking before building a fourth near-identical endpoint).

---

# Revision History

| Version | Date | Notes |
|---|---|---|
| 1.0 | 09/08/2026 | Initial version — five gaps captured from a real logged-in session walkthrough prompt. Gap 2 fixed same day (v1.54); Gaps 1, 4, 5 scoped as roadmap/future work; Gap 3 explicitly recorded as out of scope, not built. |
