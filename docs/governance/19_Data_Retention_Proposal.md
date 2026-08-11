# 19_Data_Retention_Proposal.md

**Status:** Proposal — not approved policy, not implemented
**Author:** Claude Sonnet 5 (drafted per direct request, ORLA Notifications/Security/Retention prompt, section 11)
**Date:** 2026-08-11

---

## Purpose and how to read this document

This is a HIGH PRIORITY FOLLOW-UP, deliberately produced as documentation only. **No deletion job, TTL rule, retention cron, or destructive migration exists anywhere in this codebase as a result of this document.** Every window suggested below (72 hours, two years, two weeks, and any other figure named here) is a **product hypothesis to validate, not an approved number** — see "Explicitly out of scope" below.

This inventory was built by reading the actual schema, storage clients, and application code in this repository (`backend/app/models/`, `backend/app/storage/`, `backend/app/billing/`, `backend/app/email/`, migration history) — not assumed from the prompt's own suggested numbers. Where the prompt's own hypothesis (72h / 2y / 2w) is repeated below, it is repeated as exactly that: an unvalidated hypothesis to test, flagged every time.

## Explicitly out of scope for this document (and for any near-term implementation)

- No deletion jobs, TTL rules, or scheduled purges.
- No destructive migrations.
- No changes to any retention-adjacent code path (uploads, R2, billing, audit logs).
- No legal conclusions. Every reference to "GDPR," "Irish Data Protection Act 2018," "Revenue/tax retention," or similar is a flag for **qualified legal counsel to confirm**, not a legal opinion this document is qualified to give.

---

## 1. Cross-cutting design questions to resolve before any implementation

These apply to every row below and should be answered once, centrally, rather than re-decided per data type:

1. **Deletion request intake**: is there a single "delete my data" / "delete this business" entry point a user or owner triggers, or does retention only ever fire on a timer (e.g., 7 days after `Report.expires_at`, N days after `Business.deleted_at`)? Today, `soft_delete_business` (`backend/app/repositories/business.py`) is the only user-triggered deletion-adjacent action in this codebase, and it does not cascade to any child table (confirmed: no `business_id` foreign key anywhere in this schema has `ON DELETE CASCADE` — see `06_Database_Design.md` and every model's own FK definition).
2. **Soft-delete-first, hard-delete-later, or soft-delete-only?** This codebase's existing convention (`Business.deleted_at`, `EmployeeSeat.status = "canceled"`, `ImportRecord.reversed_at`, `Notification.status = "dismissed"`) is soft-delete via a nullable timestamp/status column, never a hard `DELETE`. Any retention policy should decide, per data type below, whether it stays soft-delete-forever (current behavior for all of the above) or graduates to an irreversible hard-delete after some window — these are different commitments with different backup/legal implications.
3. **Who executes retention?** No background job scheduler beyond `backend/app/scheduler/tick.py` (report generation, freshness checks) exists today. A retention job would be new infrastructure: same tick-based reconciliation pattern (idempotent, retriable, logged) is the natural fit given precedent, but this needs its own design pass, not an assumption baked into this document.
4. **Audit trail for deletion itself**: `AuditLog` (`backend/app/models/audit_log.py`) already records `action`/`target_type`/`target_id`/`metadata` for e.g. `threshold_updated`, `employee_deleted`. Any retention/deletion job should write an equivalent audit event — itself subject to the audit-log retention question in section 12 below (a tamper-resistant record of "we deleted X" must usually outlive X).

---

## 2. Inventory, by storage location

Each entry: **Owner / Location / Purpose / Sensitivity**, then the retention-design questions the follow-up proposal needs to answer, per the prompt's own required fields.

### 2.1 Uploads and generated files — Cloudflare R2

- **Owner**: the business that uploaded the file. **Location**: Cloudflare R2 (`backend/app/storage/`, confirmed no other object store used — ADR-013 also rules out Supabase Storage). **Purpose**: raw source file for an import (sales/purchases/inventory/repairs CSV/XLSX), kept as the ground truth behind `ImportRecord`. **Sensitivity**: potentially contains customer names/emails/phone numbers if a source export includes them in columns this platform never maps or reads (e.g. a POS export's "customer" column) — the *parsed* data this platform stores deliberately excludes customer PII (confirmed throughout this session's work: `Sale`/`SaleItem`/`ProductionEvent` carry no customer name/email field), but **the original uploaded file itself may still contain it**, sitting in R2 exactly as uploaded.
- **The prompt's suggested window (72 hours) is a hypothesis to validate against**: how long does support/debugging actually need the raw file after a successful import? Does "failed" or "replaced" (a remap) leave an orphaned R2 object with no `Upload` row pointing at the *latest* version? Confirmed: `ImportRecordRepository.delete_for_upload` (remap path) deletes the DB row but this codebase's R2 client was not audited in this pass for whether the *old* object is also deleted on remap — **this needs verification, not assumption**, before any 72h window is implemented.
- Deletion trigger candidates: N hours/days after `ImportRecord.status == "completed"`; immediately on `reversed_at` (undo) once the reversal itself doesn't need the source file anymore; on `Upload.status == "failed"` after some window.
- Proof-of-deletion: R2 delete confirmation should be logged (which R2 API call, when, object key) — today, no such log exists.

### 2.2 Deleted users, linked identity, employee seats, invitations, sessions

- **Owner**: the individual (User row + Supabase Auth identity) or the business (EmployeeSeat). **Location**: `users` table (this backend, `backend/app/models/user.py`) + Supabase's own Auth tables (outside this codebase, outside this backend's control — see `backend/app/security/auth.py`'s own newly-added ownership-map comment, this session). **Purpose**: authentication identity, tenant membership. **Sensitivity**: email address (PII), name, address fields on `EmployeeSeat` (`backend/app/models/employee_seat.py` — `address_line1`, `city`, `postal_code`, `country`).
- Confirmed in this codebase: `delete_employee` (`backend/app/application/employee_seats.py`) never hard-deletes an `EmployeeSeat` row — it sets `status = "canceled"` and calls `revoke_employee_membership` (deletes the `Membership` row, which *is* a real, immediate access revocation — confirmed by this session's own isolation tests). The `EmployeeSeat` row itself, with its name/address, persists indefinitely today.
- **The prompt's suggested 72-hour deletion window + "immediate access revocation" is a hypothesis**: access revocation is already immediate (Membership deletion) — that part is arguably already correct behavior. What's unresolved is whether the `EmployeeSeat`'s own PII (name, address) should be deleted/anonymized after some window post-cancellation, and what that window should be. A local `User` row for someone who never returns has no expiry today either.
- Supabase Auth's own user/session lifecycle (password, session tokens, MFA if ever enabled) is entirely outside this backend's control — any retention policy for that layer is a Supabase project configuration decision, not something this codebase implements.
- Password-reset tokens: **entirely Supabase-owned** (see `backend/app/security/auth.py`'s architecture-mapping comment, added this session) — this backend has never stored one.

### 2.3 Deleted businesses and branches, memberships, audit history

- **Owner**: the business (and, for a branch, the parent business's owner). **Location**: `businesses` table. **Purpose**: the core tenant record. **Sensitivity**: business name, address/contact fields (`manager_first_name`, `contact_email`, `contact_phone`, `address_line1`, etc. — all added across earlier rounds this session).
- Confirmed: `soft_delete_business` sets `deleted_at`, cancels the Stripe subscription if one exists, and touches **no other table**. Every child row (products, sales, employee seats, audit logs, notifications, reports) stays exactly as it was, forever, with no expiry — a deleted business's entire operational history is currently permanent.
- Effect on owner access: a soft-deleted business simply disappears from `list_businesses_for_user` (confirmed, `deleted_at IS NULL` filter) — the owner loses the ability to see or act on it through the normal app, but every underlying row still exists and is still tenant-scoped correctly (no cross-tenant leak risk from this).
- Open question for the follow-up: does a soft-deleted business's data ever get hard-deleted, and if so, after what trigger (a fixed window after `deleted_at`? Never, and it's an intentional permanent archive?). This has real cost implications (storage) and real legal-hold implications (see section 2.9) that need to be resolved together, not independently.

### 2.4 Ingested operational records — sales, purchases, inventory, repairs, transactions

- **Owner**: the business. **Location**: `sales`, `sale_items`, `inventory_movements`, `production_events`, `returns` tables. **Purpose**: the core operational ledger every analytics/report/forecast/ORLA-chat feature reads from. **Sensitivity**: low on customer PII (confirmed repeatedly this session — no customer name/email anywhere in these tables, only a nullable `customer_id` FK that's never populated by any import path today), but commercially sensitive (a shop's actual revenue/margin/supplier terms).
- **The prompt's suggested "maximum two-year retention" is a hypothesis, and a consequential one**: this data is the *entire* basis for every forecast (which uses lookback history — `app/analytics/forecasting.py`), every trend/weekly-performance comparison (this session's own new `_MIN_WEEKS_OF_HISTORY = 4` gate), and every "how does this compare to a year ago" question a future feature might ask. A 2-year cap would need to be checked against: (a) genuine accounting/tax retention obligations in Ireland (typically 6 years for business records — **verify with an accountant/tax advisor, not assumed here**), (b) whether any current or planned feature does year-over-year comparison beyond 2 years, (c) whether "retention" here means hard deletion or migration to cold/archival storage (a very different cost and recoverability profile).
- No existing code enforces any retention on this data today — every row written by an import stays until an explicit `undo` (which already exists, `ImportRecordRepository`/`app/imports/importer.py`, and is itself a form of user-triggered deletion, already built and tested).

### 2.5 Generated reports and report export files

- **Owner**: the business. **Location**: `reports` table (`Report.payload`, a JSON blob) + this session's own new PDF/DOCX export files (generated on-demand, not persisted anywhere — confirmed: `render_report_pdf`/`render_report_docx`, `backend/app/exports/`, return bytes directly in the HTTP response, never written to R2 or disk).
- Confirmed existing behavior: `Report` rows are **never hard-deleted** — `expires_at` (7 days after generation, `_REPORT_EXPIRY_DAYS` in `backend/app/application/report.py`) only controls whether `list_active_for_business`/`get_report` (and, as of this session, the new PDF/DOCX download routes, which reuse the exact same availability check) will *serve* the report — the row itself, `payload` and all, persists indefinitely as "its own operational audit record" (the existing code's own docstring language, `backend/app/repositories/report.py`).
- **The prompt's suggested "two-week retention... now that users can download PDF/DOCX copies" is worth flagging as already partially inconsistent with current behavior**: today a report becomes inaccessible via the API after 7 days (not 14), but the underlying row is never deleted at all — there is no "two-week" anything currently implemented to shorten. If the intent is "give users 14 days to download a copy before the row itself is hard-deleted," that is a **new, distinct decision** (shortening/adding a hard-delete on top of today's soft "goes inactive after 7 days, row persists forever") — not a tightening of an existing 2-week window, because no such window exists yet.
- Since PDF/DOCX exports are generated on-demand and never stored server-side (confirmed above), there is no separate "export file" retention question today — only the underlying `Report.payload` row's own lifecycle matters.

### 2.6 Products, suppliers, product-supplier relationships, thresholds

- **Owner**: the business. **Location**: `products`, `product_categories`, `suppliers`, `product_suppliers` tables. **Purpose**: the catalogue backing every stock/reorder feature. **Sensitivity**: low — no customer PII; supplier `contact_info` (confirmed, `backend/app/models/supplier.py`) is the only arguably-sensitive field, and it's a business contact, not a personal one in the typical case.
- No retention question distinct from section 2.3/2.4 above — these rows live and die with the business/branch they belong to, and are not independently time-bound today (a "deleted" supplier is soft-deleted via `status`, matching the rest of this schema's convention — confirmed, `SupplierRepository`).

### 2.7 ORLA insights, derived analytics, cached aggregates, embeddings/search indexes

- **Confirmed finding, stated plainly**: **none of these exist as persisted data in this codebase.** Every dashboard/report/forecast/findings number is computed on read, from the raw operational tables in section 2.4, every time (CLAUDE.md's Core Rule: "deterministic Python calculates" — confirmed throughout every analytics module read this session, e.g. `app/analytics/retail.py`, `app/analytics/financial.py`, `app/application/stock_review.py` built this session). There is no cache table, no materialized view, no embeddings/vector index anywhere in this schema (the global search feature built earlier this session, `app/application/search.py`, is parameterized `ILIKE` over the live tables, not a search index). The only persisted "derived" artifact is `Report.payload` (section 2.5) and `AIRequest` (section 2.10, a usage/cost log, not a cache of an answer).
- **Retention implication**: this section of the follow-up proposal can likely be marked "not applicable — no such storage exists," rather than assigned a window, unless a future feature introduces one (at which point this document should be revisited).

### 2.8 Notifications, notification delivery records, dismissed/resolved state

- **Owner**: the business (role-scoped further within it — some categories are owner-only, per this session's own permissions work). **Location**: `notifications` table. **Purpose**: the ORLA Notification Centre, built substantially this session. **Sensitivity**: low — titles/bodies are deterministic, PII-free by design (confirmed repeatedly this session, e.g. the stock-review/weekly-performance/system-status notifications built in this same round never include a customer name).
- No delivery-record table exists (no email/push delivery log — this codebase has no push notifications; the only "delivery" is the in-app row itself plus, where wired, a transactional email via Resend — see section 2.11).
- Current behavior: a dismissed notification stays in the table forever (`status = "dismissed"`, never deleted) — the same session's own new pagination work (section 6 of the notifications/security/retention prompt, built earlier in this same round) already had to account for an effectively-unbounded history, which is exactly why real `limit`/`offset` pagination was added rather than assuming a small table.
- Retention question for the follow-up: is there a real business need to keep dismissed notifications indefinitely, or should they be hard-deleted after some window (weeks? months?) now that pagination exists to browse whatever's kept? This is a low-sensitivity, low-risk one to decide.

### 2.9 Audit logs and security events

- **Owner**: the business (and the acting user). **Location**: `audit_logs` table. **Purpose**: compliance/security trail (explicitly distinct from `Notification` — see `backend/app/models/notification.py`'s own docstring on this split, confirmed this session). **Sensitivity**: records *who did what* — inherently references user identity, sometimes with a `metadata` payload (e.g. `{"threshold_days": ...}`) that could grow to include more detail over time.
- **The prompt's own instruction is correct and should be followed literally**: audit logs "may require a different tamper-resistant retention period" — almost certainly **longer**, not shorter, than the operational data they describe, since their entire purpose is to prove what happened *after* the fact, including after other data has been deleted or anonymized. A retention policy that deletes a `Product` after 2 years but an audit log entry referencing that product's `target_id` after (say) 90 days would leave an audit trail with dangling, unverifiable references — the ordering/asymmetry between these two retention windows needs explicit design, not an assumption that "shorter is safer."
- No tamper-resistance mechanism (e.g. append-only enforcement, hash chaining, write-once storage) exists in this schema today — `audit_logs` is a normal, updatable/deletable Postgres table like any other. If audit-log integrity is a real compliance requirement, that's a distinct, larger piece of work from retention timing alone.

### 2.10 Billing/subscription records, Stripe identifiers, invoices, webhook records

- **Owner**: the business (and, indirectly, Anthropic... no — the platform operator). **Location**: `subscriptions`, `employee_seats` (Stripe fields), `processed_stripe_events` tables; actual invoices/payment records live in Stripe itself, not this database (confirmed — this backend stores `stripe_customer_id`/`stripe_subscription_id`/status only, never card details or full invoice line items, consistent with never handling raw payment data directly). **Purpose**: subscription state, webhook idempotency (`processed_stripe_events` — confirmed this exists specifically to make webhook handling idempotent, `backend/app/models/billing.py` area). **Sensitivity**: no card data ever touches this backend; Stripe IDs alone are not independently sensitive but do link to a real payment history in Stripe.
- **The prompt's own instruction must be followed here too, without exception**: "Do not delete records that must be retained for tax, accounting, fraud or dispute obligations." Financial/subscription records are the single category in this entire inventory most likely to have a **hard legal minimum retention** (commonly multi-year for tax/accounting purposes in most jurisdictions, Ireland very likely included) that would **override** any product-driven "delete after N days" preference entirely. This category should be the **first** one validated with an accountant/qualified advisor before any implementation, not the last.
- `processed_stripe_events` (webhook idempotency keys) is a different case — its only purpose is preventing a replayed webhook from double-applying, so it plausibly has a much shorter useful life (once past Stripe's own webhook-retry window) than the subscription record itself. These two should not share one retention window by default.

### 2.11 Transactional email logs, processing logs, analytics/telemetry, error monitoring, support records

- **Owner**: platform operator (mostly) / business (email content itself). **Location**: Resend (the email provider — `backend/app/email/`, confirmed this session's earlier work built a Resend client with "graceful degradation," meaning email failures don't block the underlying action) holds its own delivery logs, outside this codebase. **Purpose**: invite emails, any future transactional security email (this document's own section 4 findings note that password-reset/email-changed notifications are not currently wired to email at all, pending the Supabase Auth Hooks gap already disclosed in code). **Sensitivity**: email addresses, names, invite context.
- No local database table logs outbound email content or delivery status today (confirmed — the Resend client call is fire-and-forget from this backend's perspective, with the *outcome* reflected in `AuditLog`/`Notification`, not a dedicated email log table).
- No error-monitoring/telemetry system (e.g. Sentry) is integrated in this codebase today — application logs go to stdout (`logger.exception`/`logger.warning` throughout, confirmed extensively this session), captured only by whatever the deployment platform does with container logs. Retention of *that* is an infrastructure/deployment decision (e.g. a hosting platform's own log retention setting), not something this codebase controls or should assume a number for.
- `AIRequest` (`backend/app/models/ai_request.py`) is the one real "processing log" in this schema — every AI provider call, cost, and success/failure, used this session to build the platform-wide "ORLA insights unavailable" health check. Its retention question is really a usage-analytics one (how long is historical AI cost/usage data useful to keep at row-level detail vs. aggregated) rather than a PII one — it carries `user_id`/`business_id` but no message content.

### 2.12 Database backups, R2 versioning, replicas, caches, search indexes, disaster-recovery copies

- **Confirmed**: this codebase has no knowledge of or control over its own hosting platform's backup/replication configuration (Neon for Postgres, per `CLAUDE.md`'s stack list; Cloudflare R2's own versioning settings for object storage). **This entire section can only be answered by whoever administers those platforms' dashboards/settings** — it is not discoverable from the application code, and this document does not fabricate an answer.
- The prompt's own explicit requirement — "including the delay before deleted data disappears from backups" — is the single most important open question for GDPR-style "right to erasure" compliance, and it is **entirely outside this codebase's visibility**. Any retention policy that promises "deleted within X" to a customer must account for how long a *backup* copy could still restore that data, which depends on Neon's/R2's own retention settings, not on anything this application does.

---

## 3. Required fields for the eventual follow-up proposal, per data type above

The prompt asks the eventual (still-not-written) approved policy to define, per storage location:

- Data owner, storage location, purpose, sensitivity — **provided above for each type**.
- Retention trigger and exact window — **deliberately left open above**; every number floated in this document is a hypothesis, not a decision.
- Soft deletion vs. irreversible deletion — **current behavior is soft-delete-only, everywhere, forever**, as inventoried above; whether any category graduates to hard-delete is the single biggest open decision.
- Immediate access-revocation behaviour — **already correct today for Membership removal** (confirmed via this session's own isolation tests); not yet defined for any other category.
- Cascade/anonymisation rules and referential-integrity effects — **no FK in this schema cascades today** (confirmed, zero `ON DELETE CASCADE` anywhere) — any hard-delete design must explicitly handle every child table itself, or risk a bare FK-violation crash exactly as flagged in an earlier planning pass this session (see the "one shop per account" plan's own finding, recorded in this session's history, that a naive hard business-delete would fail immediately for this reason).
- User export requirements before deletion — **no export/download-my-data feature exists today** (the PDF/DOCX report export built this session is the closest analogue, but it's report-scoped, not account-scoped).
- Legal hold, billing/accounting, and security exceptions — **flagged explicitly above for billing (2.10) and audit logs (2.9)** as the two categories most likely to need a carve-out from any general policy.
- Background-job scheduling, retries, idempotency, failure alerts — **no such job exists today**; `app/scheduler/tick.py`'s own idempotent-reconciliation-pass pattern (retry-safe, logs-and-continues on a single failure, never aborts the whole run) is the closest existing precedent and the most natural starting point for a retention job's own design, not a decision this document makes on the eventual implementer's behalf.
- Proof-of-deletion and auditable records that do not recreate deleted personal data — **not designed here**; note the tension already flagged in 2.9 between "audit logs should outlive the data they describe" and "an audit log referencing a deleted person's data must not itself become a backdoor copy of that data" — these two requirements need to be reconciled explicitly (e.g. an audit entry that records "user X's data was deleted" by ID/hash, never by re-storing the deleted content).
- Admin/user UX, warnings, grace periods, cancellation/recovery window, final confirmation — **no UX exists for any of this today** beyond the existing "Delete this shop" confirmation flow (`frontend/app/onboarding/page.tsx`, inline Yes/No, no grace period, immediate soft-delete + Stripe cancellation) — worth deciding whether that's the right pattern to extend to every other deletable entity, or whether higher-stakes deletions (e.g. an eventual hard-delete) need a longer, more deliberate confirmation/grace-period UX than the current one-click-plus-confirm shop deletion.
- Backup expiry and third-party deletion propagation — **outside this codebase's visibility**, per section 2.12.
- Tests for tenant isolation, partial failures, restoration risks, accidental cross-tenant deletion — **not written**, since no implementation exists yet; whatever retention job is eventually built should follow this session's own established convention of a dedicated `tests/tenant_isolation/` suite proving a retention job for business A can never touch business B's rows, alongside integration tests for the job's own idempotency/retry behaviour (matching `app/scheduler/tick.py`'s own existing test coverage as the closest precedent).

---

## 4. Recommended next step

Before any implementation:

1. Get the two genuinely legally-consequential categories — **billing/tax records (2.10)** and **operational-ledger retention for accounting purposes (2.4)** — in front of a qualified accountant/tax advisor and, for the EU/Irish data-protection angle specifically, qualified legal counsel. These two answers constrain almost everything else (a shorter product-driven window can never override a longer legal minimum).
2. Confirm the actual backup/versioning/replication retention configured today in Neon and Cloudflare R2 (an infrastructure-console question, not a code question) — this bounds what "deleted" can honestly mean in any customer-facing communication.
3. Only then design the deletion-trigger/window/cascade mechanics for the remaining, lower-stakes categories (notifications, dismissed audit-adjacent UI state, stale draft data) — these carry the least legal risk and the most room for product judgment.
