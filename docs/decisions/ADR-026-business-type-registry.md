# ADR-026: One backend registry of business types with capability flags; core code asks capabilities, never industry names

**Status:** Accepted (implemented)
**Date:** 2026-11-12
**Related:** PD-011, BD-002, ADR-002, PD-010, `backend/app/templates/__init__.py`, `backend/app/api/business_templates.py`, Jira ORLA-71

## Context

Sign-up offered a single hard-coded type ("Bicycle shop"), contradicting BD-002/PD-001 (multi-industry platform). The backend stored any string as `Business.template` without validation, and three core services (AI, reports, search) compared `template == "bicycle_shop"` to decide whether repairs/workshop features apply — industry logic inside core services, against CLAUDE.md's non-negotiables.

## Decision

- `backend/app/templates/__init__.py` is the single source of truth: each type has a `key`, `label`, `description`, `group` ("Retail" / "Food & drink") and capability flags (today: `supports_repairs`).
- The frontend loads the list from `GET /business-templates` and never hard-codes it. `BusinessCreate` rejects unknown keys (and unknown timezones).
- Core code calls `template_supports_repairs(key)` / `template_label(key)` instead of comparing keys. Businesses expose `template_label` and `supports_repairs`; the UI hides the repairs upload type, Workshop Performance and the repairs tab when false.
- 19 types at launch (PD-011): 13 retail (5 with repairs/servicing), 6 food & drink. Every type gets the shared core (sales, stock, purchases, suppliers, forecasting, findings, ORLA).
- ORLA's explain prompt is told the business's type label so wording fits (it never changes which numbers are fetched).

## Consequences

- Adding a vertical is one registry entry; new modules are new capability flags.
- Food & drink types run on retail analytics until recipe costing, waste and expiry exist (ORLA-83).
- Legacy stored keys that are no longer listed still display (raw key) and get no optional modules.

## Alternatives Considered

- **Per-template Python packages with their own services:** heavier than needed while the only difference is one module flag.
- **Frontend-only list:** would duplicate the source of truth and leave the backend unvalidated.

## Review Trigger

A type needing behaviour that a boolean flag can't express (e.g. recipe costing for food & drink), or a pharmacy launch once Q-053 is resolved.
