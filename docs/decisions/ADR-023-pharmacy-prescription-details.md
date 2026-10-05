# ADR-023: Add a pharmacy prescription_details business-template extension

**Status:** Accepted — **on hold (05/10/2026, PD-011)**
**Date:** 2026-08-04
**Related:** `docs/governance/06_Database_Design.md`, `docs/governance/12_Decision_Register.md` (PD-010), `docs/governance/17_Open_Questions.md` (Q-053)

## Update 05/10/2026 — on hold, PSI permission required (PD-011)

ORLA will **not** build prescription or dispensing features for pharmacies in the near future. Before anything that captures, stores, or processes prescription data is built, ORLA needs proper permission/engagement with the **Pharmaceutical Society of Ireland (PSI)**, in addition to the GDPR legal-basis/DPIA/retention work already blocking this under Q-053.

Practical consequences:

- `prescription_details` stays exactly as it is — a schema-only model that **no repository, service, route, import, or UI reads or writes** (confirmed in code on this date: it is referenced only by `app/models/`). It must stay that way until PD-011 is lifted.
- No import entity type, field alias, dashboard section, report content, or Ask ORLA intent may be added for prescription data, controlled-substance schedules, or prescribers.
- Pharmacies remain a supported *retail* vertical (sales, stock, purchasing, forecasting, reports). This hold is only the prescription-level layer.
- Whether to keep or drop the unused table is deliberately left open; dropping it is an additive-safe migration if the team prefers not to carry an unused special-category-shaped schema.

This ADR's original decision text below is preserved as the design to revisit once permission exists.

## Decision

Add `prescription_details` — a thin business-template extension table hanging off `sale_items` (`sale_item_id` FK, unique; `prescription_number`, `prescribing_doctor`, `controlled_substance_schedule`), per the three-layer model's convention that template-specific data lives in a separate table referencing the canonical layer, not columns bolted onto `sale_items` itself. One row per `sale_item` — a multi-drug prescription is several `sale_items` sharing one `prescription_number`.

**Deliberately excludes patient identity/clinical fields** — no name, date of birth, or diagnosis.

## Reason

Pharmacy is a real target vertical. A dispensing pharmacy's genuine schema gap versus the existing canonical model is regulatory record-keeping on individual sale lines, not a production/consumption pattern (see ADR-016's decision record — pharmacy was validated as *not* needing Production Events, only this and ADR-022).

## Alternatives Considered

**Store prescription fields directly on `sale_items`.** Rejected — bicycle-shop and cafe tenants would carry permanently-null pharmacy columns on a canonical table, violating the "no bicycle-specific [or single-industry] assumptions in core services" rule (CLAUDE.md) applied to any single industry.

**Capture full patient records (name, DOB, medical history).** Rejected outright — not requested by the schema's actual need (linking a sale line to a prescription for regulatory record-keeping), and directly contrary to Company Constitution Principle 7 ("Customer Data Is Sacred") and the platform's existing data-minimisation practice in ingestion. A pharmacy's own external system remains the record of patient identity.

## Consequences — read before building anything on this table

**This decision does not resolve GDPR compliance.** Prescription data is a GDPR Article 9 special category. Minimal fields reduce exposure but do not by themselves make the table compliant: it is still linkable to an identifiable customer via `sale_items -> sales -> customers`. Legal basis, a DPIA, and a retention/deletion policy are unresolved — tracked as Q-053 (`docs/governance/17_Open_Questions.md`) and R-036 (`docs/governance/16_Risk_Register.md`), explicitly blocked on legal/DPO advice, not an engineering decision. **Do not build a pharmacy-facing feature that writes to this table before Q-053 is resolved.**

## Future Review Criteria

Revisit once legal/DPO advice is obtained (Q-053) — the resolution may require additional fields (e.g. explicit consent record) or a different storage/retention treatment than the rest of the schema.
