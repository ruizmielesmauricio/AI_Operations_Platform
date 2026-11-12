# ORLA Acceptance Criteria

**Status:** Approved 12/11/2026. Tests written (Stage 2). Protected from edits by the autobuild loop.
**Derived from:** `docs/governance/` (00, 03, 04, 05, 06, 09, 10, 12, 18, 19), `docs/decisions/ADR-0xx`, `CLAUDE.md`.
**Rule:** a criterion is met only when its test passes against real, running behaviour. Nothing here is "Done" because code exists.

Priority: **P0** = non-negotiable / launch-blocking · **P1** = PRD commitment · **P2** = NFR or quality bar.
Backend tests: `tests/acceptance/` (pytest). Frontend tests: `tests/acceptance-e2e/` (Playwright).

## 1. Tenancy isolation

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-001 | Every tenant-owned table has a non-null `business_id` column (allow-list only for shared-core tables: `users`, `processed_stripe_events`, …). | CLAUDE.md; ADR-012; 03 Multi-Tenancy | P0 | `tests/acceptance/test_tenancy.py::test_every_tenant_table_has_business_id` |
| AC-002 | For **every** registered business-scoped API route (enumerated from the FastAPI app, so new routes are covered automatically), a member of business A calling it for business B gets 403/404 and the body contains no B data. | PR-6.1; ED-008 | P0 | `tests/acceptance/test_tenancy.py::test_cross_tenant_access_denied_on_every_route` |
| AC-003 | A `business_id` supplied by the client (path, query or body) is never trusted: membership is checked server-side; a forged id in a body/query on A's own route cannot read or write B. | PR-6.2 | P0 | `tests/acceptance/test_tenancy.py::test_forged_business_id_rejected` |
| AC-004 | Every non-public route returns 401 without a valid token (public allow-list: health, Stripe webhook). | PR-6.2; ADR-013 | P0 | `tests/acceptance/test_tenancy.py::test_unauthenticated_requests_rejected` |
| AC-005 | ORLA chat for business A never includes business B data in the context sent to the AI gateway, and the `ai_requests` row is logged under A. | PR-6.1; PR-5.2 | P0 | `tests/acceptance/test_tenancy.py::test_ai_context_is_tenant_scoped` |
| AC-006 | "All branches" group views include only branches of a parent the caller is a member of; a branch of another owner is never included. | BD-007; 03 Multi-Tenancy | P0 | `tests/acceptance/test_tenancy.py::test_branch_group_scoped_to_member` |

## 2. AI explains only (Business Logic First)

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-007 | No AI provider/router SDK import or provider URL (openrouter.ai, openai, anthropic, …) appears anywhere outside `backend/app/ai/`. | ED-006; ADR-006 | P0 | `tests/acceptance/test_ai_boundary.py::test_no_provider_sdk_outside_ai_package` |
| AC-008 | No calculation or data-transformation path imports `app.ai`: `analytics/`, `forecasting/`, report generation, scheduler, alerts and the importer's row-transformation code have zero imports of `app.ai` (only the one-off column-mapping suggestion may). | PR-6.4; ED-009; ADR-007 | P0 | `tests/acceptance/test_ai_boundary.py::test_calculation_paths_do_not_import_ai` |
| AC-009 | When the model returns a numeric claim not present in the structured context, the guardrail blocks or flags it before it reaches the user. (Provider stubbed at the HTTP boundary; the guardrail is the thing under test and runs for real.) | PR-5.3; 05 | P0 | `tests/acceptance/test_ai_boundary.py::test_unsupported_number_is_blocked` |
| AC-010 | Every ORLA answer records which approved query function or help-KB entry it came from; a question with no approved source gets a plain "can't answer that" with no figures. | PR-5.6; ADR-020; PD-008 | P0 | `tests/acceptance/test_ai_boundary.py::test_every_answer_traces_to_approved_source` |
| AC-011 | With the AI provider down, dashboard/analytics endpoints still return full metrics and chat returns a clear plain-language "unavailable" message (no 500). | PR-5.4 | P0 | `tests/acceptance/test_ai_boundary.py::test_ai_outage_degrades_gracefully` |
| AC-012 | A per-tenant AI usage limit of **300 questions per business per calendar month** (configurable setting) is enforced server-side (machine-readable error code when exceeded), and every AI call is logged with provider, model, tokens, cost, feature, business, user, success. | PR-5.5; 05 | P1 | `tests/acceptance/test_ai_boundary.py::test_per_tenant_ai_limit_and_logging` |
| AC-013 | Scheduled report generation makes zero AI gateway calls (gateway patched to raise; report still generates). | PR-8.7; ADR-019 | P0 | `tests/acceptance/test_ai_boundary.py::test_report_generation_never_calls_ai` |
| AC-014 | AI column-mapping suggestion is used once per source; the confirmed mapping is stored and the second upload from the same source triggers no AI call and no user mapping input. | ED-009; PR-2.5 | P1 | `tests/acceptance/test_ai_boundary.py::test_mapping_suggestion_used_once` |

## 3. Industry-agnostic core

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-015 | No bicycle-specific literals (`bike`, `bicycle`, `mechanic`, …) or hard-coded `template == "<vertical>"` branches in core code: `backend/app/**` outside `templates/`, and `frontend/**` outside template config. Behaviour differences come from template config. | CLAUDE.md; BD-002; PD-001 | P0 | `tests/acceptance/test_industry_agnostic.py::test_no_vertical_specific_logic_in_core` |
| AC-016 | No core table or column is named for a single industry (e.g. `repairs`, `bike_*`, `prescription*` outside a template-extension table); core model has no default template — the business type is required at signup (decision 12/11/2026). | 06 Governance Rule; ADR-016 | P0 | `tests/acceptance/test_industry_agnostic.py::test_core_schema_is_industry_neutral` |
| AC-017 | A non-bike business (e.g. `coffee_shop`) can go end-to-end — create, upload sales, view dashboard, get weekly report — with no bicycle terminology in any API response. | BD-002; 06 Worked Example | P0 | `tests/acceptance/test_industry_agnostic.py::test_non_bike_business_end_to_end` |
| AC-018 | Template-specific sections (e.g. workshop/production) are omitted — not filled with placeholders — for templates that don't enable them, driven by template config. | PR-8.3; 06 | P1 | `tests/acceptance/test_industry_agnostic.py::test_inapplicable_sections_omitted` |
| AC-019 | UI terminology adapts to the template: a coffee-shop user sees no "repair", "mechanic" or "bike" text on dashboard, uploads, reports or nav. | PR-1.2; 06 Customer Perspective | P1 | `tests/acceptance-e2e/industry.spec.ts › AC-019 terminology adapts to template` |

## 4. Schema-agnostic ingestion

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-020 | CSV, XLS and XLSX all import; shuffling column order produces identical stored rows. | PR-2.1; PD-006 | P0 | `tests/acceptance/test_ingestion.py::test_formats_and_column_order` |
| AC-021 | Header row detected with up to 10 junk rows (titles, blanks, report metadata) above it. | PR-2.2 | P0 | `tests/acceptance/test_ingestion.py::test_header_detection_with_junk_rows` |
| AC-022 | Known aliases ("Item", "Product", "Description", "Product Name", "SKU Description", …) map to canonical fields with no user input. | PR-2.3 | P0 | `tests/acceptance/test_ingestion.py::test_known_aliases_auto_map` |
| AC-023 | An unmatched required column produces a plain-language question ("Which column is the sale date?") with three sample values from the file. | PR-2.4 | P1 | `tests/acceptance/test_ingestion.py::test_unmatched_column_plain_language_prompt` |
| AC-024 | Second upload from the same source needs zero mapping input. | PR-2.5 | P0 | `tests/acceptance/test_ingestion.py::test_saved_mapping_reused` |
| AC-025 | Dates (DD/MM/YY, MM-DD-YYYY, ISO), currency symbols, thousand separators, decimal commas, whitespace and mixed case normalise to correct `Decimal`/`date` values without asking. Ambiguous dates (e.g. `03/04/25`) take their day/month order from unambiguous dates in the same file; if none exist, day-first; the chosen order is shown in the import summary. | PR-2.6 | P0 | `tests/acceptance/test_ingestion.py::test_format_normalisation` |
| AC-026 | Blank rows, merged cells, subtotal rows, footer rows, duplicate mid-file headers and trailing notes are excluded. | PR-2.7 | P0 | `tests/acceptance/test_ingestion.py::test_messy_rows_excluded` |
| AC-027 | Every excluded row is counted and categorised with a plain-language reason; rows in = imported + skipped (nothing silently dropped, no stack traces). | PR-2.8; PR-2.9 | P0 | `tests/acceptance/test_ingestion.py::test_every_row_accounted_for` |
| AC-028 | Uploaded file is deleted from object storage after a successful import. | PR-2.10; ADR-008; NFR-5 | P1 | `tests/acceptance/test_ingestion.py::test_file_deleted_after_import` |
| AC-029 | Undo reverses an import transactionally, restoring prior state including stock levels. | PR-2.11 | P1 | `tests/acceptance/test_ingestion.py::test_undo_restores_prior_state` |
| AC-030 | Importing the same file twice does not double-count; a failure mid-file leaves no partial rows. | CLAUDE.md (imports transactional + idempotent) | P0 | `tests/acceptance/test_ingestion.py::test_import_idempotent_and_transactional` |
| AC-031 | Customer name/email/phone columns in an upload are never stored. | 10 Risks; Constitution P7 | P1 | `tests/acceptance/test_ingestion.py::test_customer_pii_not_imported` |
| AC-032 | End-to-end: user uploads a messy real-shaped CSV in the browser and sees an import summary with imported and skipped counts. | PD-006; PR-2.8 | P0 | `tests/acceptance-e2e/uploads.spec.ts › AC-032 messy csv imports with summary` |

## 5. Scheduled reports (weekly Monday, monthly 1st)

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-033 | Weekly report becomes due Monday 08:00 business-local time (incl. across DST, non-Dublin zones), covers previous Mon–Sun, and is not generated before then. | PR-8.1; 03 | P0 | `tests/acceptance/test_reports.py::test_weekly_due_monday_0800_local` |
| AC-034 | Monthly report becomes due on the 1st at 08:00 local, covering the previous calendar month. | PR-8.2 | P0 | `tests/acceptance/test_reports.py::test_monthly_due_first_0800_local` |
| AC-035 | When Monday is the 1st, two separate reports and two notifications are created. | PR-8.3 | P0 | `tests/acceptance/test_reports.py::test_coinciding_schedules_two_reports` |
| AC-036 | Running the scheduler tick repeatedly yields exactly one report per (business, type, period), enforced by a DB constraint. | PR-8.8 | P0 | `tests/acceptance/test_reports.py::test_generation_idempotent` |
| AC-037 | Delivery is in-app only: generation sends no email and creates no file object. | PR-8.4; PD-007 | P0 | `tests/acceptance/test_reports.py::test_in_app_only_no_email_no_file` |
| AC-038 | Report is available 7 days; its notification states the exact expiry date; after expiry the payload is not served but an audit record (status, attempts, timestamps, notification state, failure reason) remains. | PR-8.5; PR-8.12 | P1 | `tests/acceptance/test_reports.py::test_seven_day_expiry_and_audit_record` |
| AC-039 | PDF and Word are produced only on explicit request, return valid files, and are member-only. | PR-8.6 | P1 | `tests/acceptance/test_reports.py::test_on_demand_exports` |
| AC-040 | Transient failures retry with a bounded policy; persistent failure creates an operator alert carrying tenant, type, period, attempts, reason. | PR-8.9; PR-8.11 | P1 | `tests/acceptance/test_reports.py::test_bounded_retry_and_operator_alert` |
| AC-041 | A deliberately missed run is detected and regenerated by the recovery pass. | PR-8.10 | P0 | `tests/acceptance/test_reports.py::test_missed_report_recovered` |
| AC-042 | Report content matches an independent calculation on a fixture: top/bottom 3 products (ranked by units and by revenue), revenue/profit/expenses (expenses = what the business paid for the goods it sold), prior-period comparison, deterministic summary, projections, rule-based recommendations, low-stock, period + freshness + data warnings. | PR-8.3; PR-8.7 | P0 | `tests/acceptance/test_reports.py::test_report_content_matches_fixture` |
| AC-043 | User opens the reports list, opens a report, and sees its expiry date in the browser. | PR-8.4; PR-8.5 | P1 | `tests/acceptance-e2e/reports.spec.ts › AC-043 open report shows expiry` |

## 6. Billing — €80/month Stripe subscription (test mode)

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-044 | Checkout creates a subscription-mode session against a Stripe **test-mode** price that is €80.00 EUR, monthly recurring; the session explicitly offers card first (incl. Apple Pay / Google Pay), SEPA Direct Debit second, Revolut Pay third, and nothing else; automatic tax enabled. Verified against the Stripe test API. | PR-7.1; BD-005; ADR-011 | P0 | `tests/acceptance/test_billing.py::test_checkout_80_eur_card_and_sepa` |
| AC-045 | Paid access is granted only by a signature-verified webhook; the success redirect alone grants nothing; a bad signature is rejected 400. | PR-7.2 | P0 | `tests/acceptance/test_billing.py::test_access_only_from_verified_webhook` |
| AC-046 | Replaying the same webhook event is processed once. | ADR-011; CLAUDE.md idempotency | P0 | `tests/acceptance/test_billing.py::test_webhook_idempotent` |
| AC-047 | Owner can open the Stripe Customer Portal; non-owners are refused. | PR-7.3; PR-6.3 | P1 | `tests/acceptance/test_billing.py::test_customer_portal_owner_only` |
| AC-048 | An additional branch subscribes as its own €30/month subscription through the same checkout/webhook path. | BD-007 | P1 | `tests/acceptance/test_billing.py::test_branch_addon_30_eur_separate_subscription` |
| AC-049 | Billing refuses to run with a live key (`sk_live_`) unless `ENVIRONMENT=production`; the loop environment is test mode. | User instruction; ADR-011 | P0 | `tests/acceptance/test_billing.py::test_live_key_refused_outside_production` |
| AC-050 | Owner on an unpaid business is shown the subscribe flow and reaches Stripe Checkout (test mode) in the browser. | PR-7.1 | P1 | `tests/acceptance-e2e/billing.spec.ts › AC-050 unpaid owner reaches checkout` |

## 7. Auth and roles

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-051 | Backend verifies Supabase JWTs (signature, expiry, audience); forged, expired or wrong-audience tokens → 401. | ADR-013; ADR-024 | P0 | `tests/acceptance/test_auth.py::test_jwt_verification` |
| AC-052 | Signup requires choosing a business type and yields user, business (with that type) and an `owner` membership; signup without a type is rejected. | PR-1.1 | P0 | `tests/acceptance/test_auth.py::test_signup_creates_owner_membership` |
| AC-053 | Role permissions are enforced server-side: staff calling owner/manager endpoints directly (business edit, billing, employees, thresholds, suppliers) get 403. | PR-6.3 | P0 | `tests/acceptance/test_auth.py::test_role_permissions_server_side` |
| AC-054 | Supabase is used for identity only: backend has no Supabase DB/storage client and `DATABASE_URL` is never a Supabase host. | ADR-013 | P0 | `tests/acceptance/test_auth.py::test_supabase_auth_only` |
| AC-055 | Owner invites a user with a role; invite email goes through the email boundary (Resend); invitee gets exactly that role. | PR-1.5 | P1 | `tests/acceptance/test_auth.py::test_invite_with_role` |
| AC-056 | Browser: logged-out user is redirected to login; valid login lands on the app; logout ends the session. | ADR-013 | P0 | `tests/acceptance-e2e/auth.spec.ts › AC-056 login, redirect, logout` |
| AC-057 | Password reset signs out the user's other sessions. | ADR-024 | P1 | `tests/acceptance-e2e/auth.spec.ts › AC-057 password reset revokes other sessions` |
| AC-058 | New user reaches the first-upload screen after no more than 6 onboarding questions. | PR-1.3; PR-1.4 | P2 | `tests/acceptance-e2e/onboarding.spec.ts › AC-058 at most six questions before upload` |

## 8. Dashboards, analytics, findings, forecasts, alerts

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-059 | Metrics are deterministic and correct: same data → identical output; revenue, gross margin, stock cover match hand-computed `Decimal` values on a fixture. | PR-3.1; ED-007; ADR-007 | P0 | `tests/acceptance/test_analytics.py::test_metrics_deterministic_and_correct` |
| AC-060 | Money is `Numeric`/`Decimal` end-to-end — no `Float` money columns, no float in calculation outputs. | CLAUDE.md Conventions | P0 | `tests/acceptance/test_analytics.py::test_money_is_decimal` |
| AC-061 | With no cost data, no profit/margin figure is returned — revenue only, with an explicit flag. | PR-3.6 | P0 | `tests/acceptance/test_analytics.py::test_no_profit_without_cost_data` |
| AC-062 | Each module payload contains status, trend, drivers, risks, recommended action. | PR-3.2 | P1 | `tests/acceptance/test_analytics.py::test_module_has_five_elements` |
| AC-063 | Metrics on partial data carry a completeness/confidence flag. | PR-3.5 | P1 | `tests/acceptance/test_analytics.py::test_partial_data_flagged` |
| AC-064 | Drill-down returns the underlying transaction rows behind a metric, paginated, with a server-enforced page-size cap. | PR-3.4; 18 Gap 5 | P1 | `tests/acceptance/test_analytics.py::test_drilldown_paginated_and_capped` |
| AC-065 | Findings are reproducible with a recorded rule version; every recommendation links to a source finding and its triggering metric values; recommendations are ranked by impact, where impact reflects need from historical sales (a faster seller that's running low ranks above a slower one). | PR-4.1–4.4 | P1 | `tests/acceptance/test_analytics.py::test_findings_and_recommendations_traceable` |
| AC-066 | Forecasts are deterministic, always carry low/high, and refuse (no number) below the minimum history. | PR-10.1–10.3 | P1 | `tests/acceptance/test_analytics.py::test_forecast_rules` |
| AC-067 | A low-stock alert is created when an import pushes a product below its threshold (per-product or per-category, default if unset), in-app only, deterministic. | PR-9.1–9.4; PD-009 | P1 | `tests/acceptance/test_analytics.py::test_low_stock_alert_on_import` |
| AC-068 | "What's low on stock?" in ORLA returns exactly the in-app alert set. | PR-9.5 | P2 | `tests/acceptance/test_analytics.py::test_agent_low_stock_matches_alerts` |
| AC-069 | A support question the help KB can't resolve creates a support request visible to the operator; no invented answer. | PR-5.7 | P1 | `tests/acceptance/test_analytics.py::test_unresolved_support_question_handoff` |
| AC-070 | Permission, billing and deletion actions each write an audit event. | PR-6.5 | P1 | `tests/acceptance/test_analytics.py::test_privileged_actions_audited` |
| AC-071 | Dashboard renders ECharts charts in the browser from JSON API data (no server-rendered chart images). | PR-3.3; ADR-010 | P1 | `tests/acceptance-e2e/dashboard.spec.ts › AC-071 charts render client-side from api` |
| AC-072 | Every metric shows a plain-language definition on demand. | PR-3.7 | P2 | `tests/acceptance-e2e/dashboard.spec.ts › AC-072 metric definitions on demand` |
| AC-073 | ORLA chat in the browser answers a business question with figures that match the dashboard. | PR-5.2; PD-008 | P1 | `tests/acceptance-e2e/chat.spec.ts › AC-073 answer matches dashboard figures` |

## 9. Non-functional and platform safety

| ID | Criterion | Source | Pri | Test |
|---|---|---|---|---|
| AC-074 | Dashboard API responds in < 2 s for the "typical business" fixture (see Q4 below). | NFR-1 | P2 | `tests/acceptance/test_platform.py::test_dashboard_under_2s` |
| AC-075 | A 10,000-row import completes in < 60 s. | NFR-2 | P2 | `tests/acceptance/test_platform.py::test_10k_row_import_under_60s` |
| AC-076 | Charts have text alternatives and the dashboard is keyboard-navigable (axe: no serious/critical violations). | NFR-7 | P2 | `tests/acceptance-e2e/dashboard.spec.ts › AC-076 accessible` |
| AC-077 | Dashboard is readable at 375 px wide with no horizontal scroll. | NFR-8 | P2 | `tests/acceptance-e2e/dashboard.spec.ts › AC-077 mobile readable` |
| AC-078 | Tests and the loop refuse to run against a production database: `DATABASE_URL` must be local or a Neon non-primary dev branch (guard checks host/branch marker). | User instruction; 07 | P0 | `tests/acceptance/test_platform.py::test_refuses_production_database` |
| AC-079 | No secrets in the repo: no `sk_live_`, real `sk_test_`/`whsec_`/`rk_` values, passwords in connection strings, or filled-in `.env.example` keys. | Constitution P7; user instruction | P0 | `tests/acceptance/test_platform.py::test_no_committed_secrets` |
| AC-080 | All timestamps stored in UTC (timezone-aware); each business has a timezone setting. | CLAUDE.md Conventions | P1 | `tests/acceptance/test_platform.py::test_utc_storage_and_business_timezone` |
| AC-081 | Error responses carry a machine-readable `code`. | CLAUDE.md Conventions | P2 | `tests/acceptance/test_platform.py::test_errors_have_machine_codes` |
| AC-082 | Route handlers are thin: no direct SQLAlchemy queries in `backend/app/api/`. | CLAUDE.md Non-Negotiables | P2 | `tests/acceptance/test_platform.py::test_thin_route_handlers` |

**Totals:** 82 criteria — 45 P0, 28 P1, 9 P2 · 70 backend (pytest), 12 frontend (Playwright).

## Contracts the tests define (new behaviour the loop must build to)

Where a criterion needs behaviour that has no API yet, the test fixes the shape:

| AC | Contract |
|---|---|
| AC-010 | Chat response field `source = {"kind": "query_function"\|"help_article"\|"none", "id"}`; ids registered in `app.ai.registry.APPROVED_QUERY_FUNCTIONS` / `HELP_ARTICLES` |
| AC-012 | Setting `ai_monthly_question_limit_per_business = 300`; over the limit → intent `usage_limit_reached`; resets each calendar month |
| AC-016/052 | `BusinessCreate.template` required, no model default; unknown type → 422; `GET /business-templates` → `[{"key","label"}]` incl. `bicycle_shop`, `coffee_shop`; vertical tables declared in a template's `EXTENSION_TABLES` |
| AC-023 | detect-mapping returns `questions: [{"field","prompt":"Which column is the …?","options":[{"column","sample_values":[3]}]}]` |
| AC-025 | import result has `date_order`: `day_first` \| `month_first` \| `iso` |
| AC-027 | junk rows (subtotal/total/notes/repeated header) counted in `rejection_summary` (`reasons` or `excluded`), separately from "no date" |
| AC-040 | persistent report failure → audit event `report_generation_failed` (target `report`, metadata report_type, period_start, attempts, last_error) |
| AC-042 | report payload adds `top_selling_products`, `bottom_selling_products`, each `{by_units: [3], by_revenue: [3]}`; `profit_and_expenses {revenue, expenses (= what the business paid for the goods it sold), profit}`; `data_freshness`; `warnings` |
| AC-044/048 | Checkout session `payment_method_types == ["card","sepa_debit","revolut_pay"]`, VAT-exclusive prices |
| AC-049 | a `sk_live_` key outside `ENVIRONMENT=production` → no Stripe call, error response |
| AC-062 | analytics module responses carry `module_summary {status, trend, drivers[], risks[], recommended_action}` |
| AC-068 | classifier intent `low_stock_alerts`; AI context = active low-stock alerts only |
| AC-069 | classifier intent `product_support` with no help match → intent `support_handoff` + row in `support_requests` (business_id, user_id, question, status "open") |
| AC-070 | role change audited with old and new role; webhook status change → `subscription_*` audit event; deletion → `business_deleted` |
| AC-078 | `app.settings.safety.assert_safe_database_target(url, environment, production_database_host)` raising `UnsafeDatabaseTarget`; called from `app/main.py`, `app/scheduler/__main__.py`, `migrations/env.py` |
| AC-081 | error JSON has `code` (snake_case) |

## Not automatically testable (tracked, not scored)

NFR-3 availability (99%) · NFR-4 EU data residency (vendor region config) · NFR-6 AI cost < €3/customer/month (needs real usage) · PR-1.4 "first upload within 5 minutes" (only the ≤6-question proxy is testable) · ADR-015 OpenRouter quality threshold (undefined).

## Decisions recorded (12/11/2026)

- Business type is chosen at signup; no default type (AC-016, AC-052).
- AI usage limit: 300 questions per business per month, adjustable later (AC-012).
- Ambiguous dates: infer order from other dates in the file, else day-first (AC-025).
- Checkout offers card (incl. Apple Pay / Google Pay), then SEPA Direct Debit, then Revolut Pay — common in Ireland — set explicitly in code; no Klarna/Amazon Pay/Satispay/Link (AC-044).
- Stripe product wording made industry-neutral; branch product renamed "Additional Location (Branch)".
- Mauricio's computer runs Windows: the loop runs inside WSL2 (Ubuntu), which Docker Desktop already uses.
- Tailwind / shadcn/ui: out of scope for now — reassess later. No criterion.
- Redis: not needed by any current task — reassess later. No criterion.
- Test environment: Stripe "ORLA sandbox" (test mode only); Supabase project "ORLA" with four dedicated test logins (orla-test-owner/staff/reset/onboard@example.com).
- All prices are VAT-exclusive (advertised €80 / €30 / €5 "excl. VAT"). Sandbox prices updated; the €80 price was re-created as `price_1UalfZ3tXLZkg6NfnCP9y2Um`.
- Report expenses = what the business paid for the goods it sold (AC-042).
- Top/bottom sellers can be ranked by units or by revenue — the report carries both (AC-042).
- The AI limit counts questions asked to ORLA, not internal AI calls (AC-012).
- Recommendations are ordered by impact, and impact reflects need from historical sales: of two equally low products, the faster seller ranks first (AC-065).
- The loop runs on Mauricio's computer (Docker available). Browser upload test uses the real dev bucket `aiops-uploads-dev`. Loop database: local Docker Postgres; a Neon branch check comes once everything passes.
- Old VAT-inclusive €80 price archived; `price_1UalfZ3tXLZkg6NfnCP9y2Um` is now the product's default price.
- "Typical business" for AC-074: one year of history, 5,000 sales, 500 products, 2 locations.

## Still open

- Employee seat (€5/month, max 2) has no Decision Register entry; PRD lists multi-location as deferred although branches (BD-007) are built. → Needs Mauricio, not blocking.

## Earlier notes on doc inconsistencies

1. **Tailwind and shadcn/ui are not decided anywhere.** No ADR covers them; only `14_Skills_Tools_Vendor_Stack_Checklist.md` recommends them. The frontend uses plain CSS variables (`frontend/app/globals.css`) and neither is installed. ECharts is in ADR-010/checklist and installed. → No criterion added. Should the loop migrate the UI to Tailwind + shadcn/ui?
2. **Redis is optional and undecided.** `07_Deployment_Guide.md` marks it "(opt.)"; `17_Open_Questions.md` Q-025 is still open; the scheduler polls Postgres with no queue. → No criterion added. Should Redis be required?
3. **OpenRouter is Proposed, not Accepted** (ADR-015), and its quality threshold is undefined. Criteria only enforce the accepted parts: gateway-only (ED-006), and guardrail + logging.
4. **"Typical business" is undefined for NFR-1.** I propose 12 months, 5 k sales, 500 products, 2 branches. Confirm?
5. **No number for the per-tenant AI limit** (PR-5.5). NFR-6 is a cost target, not a limit. AC-012 tests that a configurable limit is enforced. The value needs your decision.
6. **SEPA isn't explicit in code.** `backend/app/billing/client.py` leaves out `payment_method_types` and relies on Stripe Dashboard settings. AC-044 checks the session against the Stripe test API, so it depends on Dashboard config. Should the code set `["card","sepa_debit"]` explicitly instead?
7. **Employee seat price is undocumented.** `.env.example` and the code have a €5/month seat, max 2 per business. The Decision Register has no BD for it. → No criterion added. Should it be recorded as a BD?
8. **Multi-location support contradicts the PRD.** PRD "Explicit Non-Requirements" says multi-location comparison is deferred. BD-007 (branches) and the built all-branches views contradict that. AC-006 covers isolation only.
9. **Known current violations of the industry-agnostic rule.** These should make AC-015/AC-016 fail today: `models/business.py` and `schemas/business.py` default `template="bicycle_shop"`, and `application/report.py`, `application/search.py` and `ai/service.py` branch on `template == "bicycle_shop"`. When a business has no template, should the default be a neutral `generic` template, or must the template be chosen explicitly at signup?
10. **Ambiguous dates.** PR-2.6 asks for both DD/MM/YY and MM-DD-YYYY. Something like `03/04/25` can't be read correctly without a rule. I propose inferring the order per file from unambiguous rows, defaulting to day-first (Ireland), and asking the user if the whole file is ambiguous.
11. **`06_Development_Rules.md` doesn't exist** but is cited as the source of ED-005/007/008. **`11_Development_Roadmap.md` says v1.36** in its header, but other docs cite it at v1.37 and v1.56.
12. **E2E prerequisites.** Playwright tests need a running backend and frontend plus a **Supabase test project** with seeded test users. Without those credentials, all 12 e2e criteria fail and the score can't go above ~85. Do you have a Supabase dev/test project the loop may use (keys supplied via env, never committed)?
13. **Stripe live API check.** AC-044/048 call the Stripe test API, so they need `STRIPE_SECRET_KEY=sk_test_…` and the test price IDs in the loop environment.
