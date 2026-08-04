# 06_Database_Design.md

**Version:** 0.3 (Draft)
**Status:** Draft
**Phase:** Phase 1 – Company Foundation
**Author:** Founder & CTO
**Last Updated:** 04/08/2026

---

# Document Contract

## Purpose

This document explains, at a governance level, how the database is structured so that it serves multiple industries through configuration rather than redesign.

It uses two concrete, different business types — an independent bike shop and a coffee shop that bakes its own goods — to demonstrate that the same core schema can support very different operational realities (repairing a bicycle vs. producing a batch of pastries) with little to no structural change.

This document governs the data model. Table-by-table implementation detail must be maintained with the database migrations during development.

---

## Audience

* Founder
* Engineering Team
* Future Employees
* Investors

---

## In Scope

* The principle that the database must serve multiple industries without redesign
* How shared core tables, canonical entities, and template extensions work together
* A worked example contrasting bike-shop repairs with coffee-shop recipes/production
* Governance rules for adding a new canonical entity when a new business type needs one

---

## Out of Scope

This document intentionally does **not** define:

* Full table definitions, column lists, or data types (database migrations and implementation documentation)
* Migration tooling or process (see `12_Decision_Register.md`)
* Deployment or backup procedure (see `07_Deployment_Guide.md`)
* Specific business template configuration files

---

## Related Documents

* 00_Company_Constitution.md
* 02_Operational_Domains.md
* 10_Product_Requirements.md
* 12_Decision_Register.md

---

# Executive Summary (TL;DR)

The database is built in three layers: a **shared core** (every business, regardless of industry), a set of **canonical operational entities** (reusable building blocks like products, sales, customers, suppliers), and **business-template extensions** (industry-specific fields and entities that plug into the canonical layer without changing it).

A bike shop's repair workshop and a coffee shop's in-house bakery look completely different on the surface, but both are the same underlying pattern: **something is produced or performed using tracked inputs, and the output is sold.** The database should model that pattern once, and let each business template configure it differently — not build a "repairs" schema and a separate, unrelated "recipes" schema.

---

# The Three-Layer Model

```text
Shared Core (identical for every business)
   accounts, businesses, memberships, permissions, billing,
   uploads, imports, metrics, reports, alerts, ai_requests, audit_logs
        |
        v
Canonical Operational Entities (reusable, industry-agnostic)
   locations, customers, employees, products, product_categories,
   suppliers, sales, sale_items, inventory_movements,
   inventory_snapshots, purchase_orders, returns,
   production_events, production_event_inputs, production_event_outputs,
   inventory_lots
        |
        v
Business Template Extensions (industry-specific configuration)
   bicycle_shop: warranty_claims
   coffee_shop:  recipes, recipe_ingredients
   pharmacy:     prescription_details
```

(Full detail on the core and canonical layers: `06_Database_Design.md`.)

---

# Worked Example: Repairs vs. Recipes

This is the concrete case that motivates this document: bike shops need to track **repairs**, coffee shops that bake need to track **recipes**. These look unrelated at first glance, but they are the same structural pattern viewed from two industries.

## The Shared Pattern

Both are examples of **"an input transformation that consumes tracked stock and produces a sellable output."**

| Concept | Bike Shop (Repairs) | Coffee Shop (Recipes) |
|---|---|---|
| The "job" | A repair/work order | A production batch (e.g., a batch of croissants) |
| Inputs consumed | Parts used | Ingredients used |
| Who/what performs it | A mechanic | A baker, or simply "the kitchen" |
| Time dimension | Turnaround time, status history | Batch date, yield, shelf life |
| Output | A completed repair, billed to a customer | A quantity of a bakery product, added to sellable inventory |
| Cost impact | Labour + parts cost vs. price charged | Ingredient cost vs. price charged (recipe costing / margin) |
| Data-quality question | Are parts logged accurately? | Are ingredient quantities and waste logged accurately? |

## Why This Matters for the Schema

If "repairs" were built as a bicycle-specific table with bicycle-specific assumptions, adding recipes later would mean building an entirely separate, parallel structure — duplicating work and risking inconsistent metrics (e.g., margin calculated one way for repairs and a different way for recipes).

Instead, the database should introduce a reusable canonical concept — provisionally named **Production Events** — that both repairs and recipes are specific configurations of:

```text
production_events              (generic: a job or batch that consumes inputs and yields output)
production_event_inputs        (generic: what was consumed — parts, ingredients, materials)
production_event_outputs       (generic: what was produced — a completed repair, a batch of goods)
```

A bicycle-shop template configures this as: input = parts, output = one completed repair tied to one customer.
A coffee-shop template configures this as: input = ingredients, output = a quantity of a bakery product added to stock.

This keeps `sales`, `sale_items`, `inventory_movements`, and `products` completely unchanged between the two business types — only the template-level configuration and a thin extension table differ.

**Status:** Accepted (ADR-016), implemented in `backend/app/models/production_event.py`. The former bicycle-specific `repairs`/`repair_parts_used` tables have been dropped in favour of this canonical entity.

**Third-vertical validation:** pharmacy was scoped alongside cafe as the second and third verticals that triggered accepting this pattern (per this document's own stated gate — "once a second real customer segment is being actively built"). Unlike bike shops and cafes, a standard dispensing pharmacy does **not** need Production Events at all (only a compounding pharmacy, mixing raw ingredients into a custom medication, would) — its real gap is `inventory_lots` (lot/batch + expiry tracking, ADR-022) and a thin `prescription_details` template extension (ADR-023), not a production/consumption pattern. This is a useful negative data point: it confirms Production Events isn't being over-generalised to fit every vertical.

---

# Governance Rule for Adding a New Canonical Entity

Before adding a new table to support a new business type, ask:

1. **Is this pattern likely to recur in other industries?** (e.g., production/consumption of inputs recurs in bakeries, garages, and florists — so it belongs in the canonical layer, not a one-off template table.)
2. **Can this be modeled as configuration of an existing canonical entity**, rather than a new table? (Prefer extension tables and flexible attributes per `06_Database_Design.md`'s modeling rules.)
3. **Does this entity introduce bicycle-specific (or any single-industry-specific) assumptions into a shared table?** If yes, it does not belong in the canonical layer — move it to a template extension.
4. **Is there already a similar canonical entity this could extend, rather than duplicate?**

Only after these questions are answered should a new canonical entity be added, and it should be recorded as an ADR.

---

# Business Perspective

Every new industry the company enters should mean writing a business template (configuration), not extending the core schema. Recipes-for-coffee-shops is the first real test of whether the canonical layer is general enough — if it requires new core tables, that is a signal the canonical model needs to be rethought, not just extended.

---

# Customer Perspective

A coffee-shop owner should never see "repairs," "mechanics," or bicycle terminology anywhere in their instance of the product, and a bike-shop owner should never see "recipes" or "ingredients." Both should see terminology and workflows that feel purpose-built for their business, even though the same underlying tables serve both (per `01_Project_Vision.md`, "Industry-Flexible Core").

---

# Technical Perspective

The Production Events pattern (or an equivalent generalisation) should be validated against a third, different business type — for example, a garden centre or a florist making bouquets — before being finalised, to confirm it generalises past two examples rather than becoming a third special case.

---

# Commercial Perspective

Being able to support a new vertical primarily through configuration rather than schema and code changes is what makes the "Build Once, Scale Everywhere" principle (Company Constitution, Principle 8) commercially real rather than aspirational — it directly reduces the cost of expanding into automotive garages, pet shops, garden centres, and other future segments listed in `09_Business_Model.md`.

---

# Current Decisions

* Use a shared core, canonical operational entities, and business-template extensions as the three-layer database model (Accepted, per ADR-002 and ADR-012 in `12_Decision_Register.md`).
* Do not build industry-specific schemas as unrelated, parallel structures (Accepted, per Company Constitution Principle 8).
* Generalise "repairs" and "recipes" into a shared canonical concept, "Production Events" (Accepted, per ADR-016 in `12_Decision_Register.md`), rather than building each independently.
* Add `inventory_lots` as a canonical lot/batch + expiry-date extension to the inventory layer (Accepted, per ADR-022) — not pharmacy-specific, since perishables/consumables recur across verticals.
* Add pharmacy's `prescription_details` as a thin business-template extension (Accepted, per ADR-023), deliberately excluding patient identity/clinical fields — see `17_Open_Questions.md` Q-053 for the still-open GDPR compliance question this does not resolve.

---

# Why This Decision?

**Decision:** Model repairs (bike shops) and recipes/production (coffee shops) as configurations of one canonical "production event" concept.

**Reason:** Both are the same business pattern — inputs consumed, output produced and sold — and modelling them separately would violate the Industry-Flexible Core principle and create duplicate, inconsistent margin/cost logic.

**Alternatives Considered:** Building "repairs" as a bicycle-specific table (as currently described in `06_Database_Design.md`) and later building an entirely separate "recipes" table for coffee shops when that vertical is validated. Rejected because it was the exact anti-pattern the Company Constitution warns against ("Build Once, Scale Everywhere"), and would create duplicated profitability logic between the two.

**Future Review Criteria:** ~~Revisit once a third, structurally different business type (e.g., a florist or garden centre) is scoped, to confirm the canonical model still holds without further special-casing.~~ Met: pharmacy was scoped as the third vertical (see the Worked Example section above) and confirmed the model generalises correctly — it needed the canonical layer's `inventory_lots`/`prescription_details` extensions, not Production Events, which is itself evidence the pattern isn't over-fit to two examples.

---

# Risks

* ~~Generalising too early, before more than two business types exist, risks over-engineering a pattern that doesn't actually recur cleanly.~~ Resolved: cafe and pharmacy were both being actively scoped when this was accepted, satisfying the stated gate.
* `inventory_lots`/`prescription_details` are new and unused by any repository/service/route yet (schema-only, per this change's scope) — the real risk is building calculation logic against them later (Stage C9) without re-validating the shape holds once actual FEFO/prescription workflows are designed.

---

# Future Improvements

* Update `06_Database_Design.md`'s Bicycle-Shop Template section and `10_Product_Requirements.md`'s Repairs module to reference the generalised production-event pattern once accepted.
* Add a coffee-shop/bakery business template definition once customer discovery validates that segment, following the same process used for the bicycle-shop template in `15_Customer_Discovery.md`.
* Test the pattern against a third business type before finalising table names and structure in an ADR.

---

# Questions Still Open

* Should ingredient/parts costing feed directly into the Profitability domain (`02_Operational_Domains.md`) the same way for both business types, or does recipe costing need its own treatment (e.g., waste, shelf-life, batch yield variance)? Still open — deferred to Stage C9 calculation work.
* GDPR special-category compliance for `prescription_details` (legal basis, DPIA, retention/deletion policy) — see `17_Open_Questions.md` Q-053, blocked on legal advice.
* FEFO (first-expiry-first-out) consumption logic for `inventory_lots` is unbuilt — when Stage C9 designs it, does `inventory_movements.inventory_lot_id` need to become mandatory for lot-tracked products, or stay optional indefinitely?

---

# Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | TBD | Initial draft; introduced the repairs-vs-recipes worked example and proposed the generalised "Production Events" canonical entity. |
| 0.2 | 30/07/2026 | Fixed a stale `01_Product_Vision.md` filename reference (now `01_Project_Vision.md`); removed the self-referential "(detailed set)" Related Document. |
| 0.3 | 04/08/2026 | Accepted ADR-016 (Production Events): status Proposed → Accepted, implemented in `backend/app/models/production_event.py`, replacing the bicycle-specific `repairs`/`repair_parts_used` tables. Pharmacy was scoped alongside cafe as the second/third verticals that triggered acceptance, and confirmed as the third-vertical validation this document's own review criteria called for. Added ADR-022 (`inventory_lots` canonical lot/batch + expiry tracking) and ADR-023 (pharmacy `prescription_details` extension). Updated the canonical entities list, template extensions list, Current Decisions, Risks, and Questions Still Open accordingly. |
