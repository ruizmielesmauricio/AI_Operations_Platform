# ADR-022: Add a canonical inventory_lots (lot/batch + expiry-date) extension

**Status:** Accepted
**Date:** 2026-08-04
**Related:** `docs/governance/06_Database_Design.md`, `docs/governance/12_Decision_Register.md`

## Decision

Add `inventory_lots` (`product_id`, `lot_number`, nullable `expiry_date`, unique on `business_id`+`product_id`+`lot_number`) as a **canonical** inventory-layer extension, plus a nullable `inventory_movements.inventory_lot_id` FK so any movement can optionally tag the physical lot it affected. Unlike the reason-gated production-event FKs (ADR-016), this FK is orthogonal to `reason` — usable regardless of movement type.

Schema only: no FEFO (first-expiry-first-out) consumption logic is built yet, and no writer sets `inventory_lot_id` today. That's Stage C9 calculation-phase work.

## Reason

A pharmacy prospect explicitly requested lot/expiry tracking. It is not pharmacy-specific in principle — cafes with perishables and bike-shop consumables (e.g. brake fluid, tracked for recall purposes) have the same underlying need. Per `06_Database_Design.md`'s own "Governance Rule for Adding a New Canonical Entity" (question 1: "is this pattern likely to recur in other industries?"), a recurring pattern belongs in the canonical layer, not a one-off pharmacy template table.

## Alternatives Considered

**Make this a pharmacy-only template extension table.** Rejected — would need to be rebuilt as a near-duplicate canonical table the moment a second vertical (cafe perishables) needed the same capability, the exact anti-pattern ADR-016 was accepted to avoid.

**Skip lot tracking as a first-class relationship and just tag it in a free-form metadata field.** Rejected — loses referential integrity and queryability (e.g. "which lots are expiring this week" needs a real FK, not a JSON blob).

## Consequences

- `inventory_lots` exists but is unused by any current writer — same status `repairs`/`repair_parts_used` had before ADR-016 acted on them. Revisit if it sits unused past the point Stage C9 designs FEFO logic.
- `expiry_date` is nullable — a lot can be tracked purely for traceability (recall) without an expiry concept.

## Future Review Criteria

When Stage C9 designs FEFO consumption logic: does `inventory_movements.inventory_lot_id` need to become mandatory for lot-tracked products, or stay optional indefinitely? (Tracked in `06_Database_Design.md`'s Questions Still Open.)
