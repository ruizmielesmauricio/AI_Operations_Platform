# ADR-016: Generalise repairs/recipes into a canonical "Production Events" entity

**Status:** Accepted
**Date:** 2026-08-04
**Related:** `docs/governance/06_Database_Design.md`, `docs/governance/12_Decision_Register.md`, `docs/governance/11_Development_Roadmap.md` (Stage C8b)

## Decision

Replace the bicycle-shop-specific `repairs`/`repair_parts_used` tables with a canonical, industry-agnostic entity: `production_events`, `production_event_inputs`, `production_event_outputs`. Both a bike-shop repair and a cafe's kitchen production batch are the same underlying pattern — something is produced or performed using tracked inputs, and the output is sold — modelled once, configured per business template via a denormalized `event_type` discriminator (`"repair"` / `"production_batch"`).

`ProductionEventInput.cost_price_at_time` mirrors the existing `SaleItem.cost_price_at_sale` snapshot pattern. `inventory_movements` gained two new reason-gated provenance FKs (`production_event_input_id`, `production_event_output_id`), mirroring the existing `reference_id`/`import_record_id` dual-path convention.

Implemented as models + one migration only — no repository, service, API route, or calculation logic yet. That's Stage C9 work.

## Reason

Both are the same business pattern — inputs consumed, output produced and sold — and modelling them separately would violate the "Build Once, Scale Everywhere" principle (Company Constitution, Principle 8) and risk duplicate, inconsistent margin/cost logic between verticals.

This decision was explicitly gated (in `06_Database_Design.md`, when first proposed) on "a second real customer segment being actively built" before investing in the shared layer — premature generalisation from a single example (bike shops) was a known risk (see the retired risk R-013). That gate was met once cafe and pharmacy were both being actively scoped.

## Alternatives Considered

**Keep `repairs` as a bicycle-specific table and build a separate, parallel `recipes`/`kitchen_production` table for cafes when that vertical is validated.** Rejected — the exact anti-pattern the Company Constitution warns against, and would create duplicated profitability logic between the two.

**One shared table with a `type` column distinguishing sales from repairs.** Rejected — a sale and a repair have fundamentally different shapes (hand over existing stock vs. consume inputs over a duration and produce a billed output); forcing them into one table means either padding every sale row with nullable repair-only columns or losing the parts-consumed/turnaround data.

## Consequences

- `repairs`/`repair_parts_used` are dropped (confirmed unused anywhere outside their own model file before deletion — no data migration required).
- `Employee.performed_by_id` (renamed from `Repair.mechanic_id`) is the shared "who performed this" FK across verticals, per `Employee`'s own docstring, which anticipated this generalisation.
- Pharmacy was scoped as a third vertical alongside this decision and confirmed it does **not** need Production Events (only a compounding pharmacy would) — see ADR-022/ADR-023 instead. This is useful evidence the pattern isn't over-fit to two examples.

## Future Review Criteria

Revisit if a fourth vertical's "production" pattern doesn't fit this shape cleanly (e.g., requires a different input/output cardinality than one event → many inputs → zero-or-one output group).
