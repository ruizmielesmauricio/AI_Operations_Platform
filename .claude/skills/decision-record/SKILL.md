---
name: decision-record
description: Use when a change involves (or should involve) a recorded business, product, architecture, or engineering decision — new tech choice, reversing a prior call, a non-obvious tradeoff. Walks through this project's actual decision-register process instead of guessing a generic ADR format.
---

Governed by: `CLAUDE.md` ("record decisions as ADRs in `docs/decisions/`"),
`docs/governance/12_Decision_Register.md` (the canonical register — read this first).

1. **Check for an existing decision before proposing a new one.** Search
   `docs/governance/12_Decision_Register.md` and `docs/decisions/` — this project already merged two
   conflicting decision logs once because of duplicate IDs; don't reintroduce that problem.
2. **Pick the right type and next ID.** Types are `BD` (business), `PD` (product), `ADR`
   (architecture/tech/infra), `ED` (engineering standards/practices). Use the next free number for
   that type — check the register's tables, don't reuse or guess a round number.
3. **Log it in the register.** Add a row to the relevant table in `12_Decision_Register.md` with the
   ID, one-line summary, status, and source. Status is one of: Proposed, Draft, Accepted,
   Implemented, Superseded, Rejected, Deprecated.
4. **Write the full decision file if it's substantial** (not every one-line ED needs this). Put it in
   `docs/decisions/`, following the structure in `docs/templates/document_template.txt` — Document
   Contract header, Problem Statement, Decision + Reason + Alternatives Considered, Risks, Related
   Documents.
5. **Superseding, not silently overriding.** If this decision changes an existing Accepted one, mark
   the old row `Superseded` in the register with a pointer to the new ID — don't just leave two
   contradictory rows.
6. **Definition of done.** Register row added/updated with correct type+ID+status + (if substantial)
   a full decision file in `docs/decisions/` + no duplicate or contradictory entries left behind.
