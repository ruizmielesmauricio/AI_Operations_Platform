---
name: csv-import-boundary
description: Use when working on backend/app/imports/ — CSV/file upload, schema detection, column-mapping, validation, or normalisation. Enforces ED-009, the AI/deterministic boundary specific to customer data imports.
---

Governed by: ED-009 in `docs/governance/12_Decision_Register.md` ("AI may suggest column mappings but
must not clean, validate, transform, or deduplicate customer data"), sourced from
`docs/governance/10_Product_Requirements.md` PR-2, and `backend/app/imports/__init__.py`'s module
docstring.

1. **AI's only allowed role: suggest a column mapping, once.** E.g. "this CSV column `Qty` probably
   maps to `quantity`." That suggestion must be confirmed by the user before it's used — never
   auto-applied silently.
2. **Everything else is deterministic code.** Cleaning, type coercion, validation, deduplication,
   and normalisation of the actual data values are plain Python — never routed through an LLM, and
   never re-delegated to AI "to save time" on messy data.
3. **No customer-facing import template.** Per PD-006, don't build a flow that requires the customer
   to reformat their CSV to match a fixed template — the mapping step exists precisely so arbitrary
   column layouts work.
4. **Idempotency.** Re-uploading the same file (or retrying a failed import) must not duplicate rows
   — imports are transactional and idempotent per `CLAUDE.md`.
5. **Definition of done.** Column-mapping suggestion is AI-assisted and user-confirmed + all cleaning/
   validation/dedup is deterministic code with tests + re-running the same import is a no-op on
   already-imported rows.
