---
name: tenant-scoped-model
description: Use when adding a new database model/table, a new query/repository method, or an Alembic migration that touches business data. Enforces business_id tenant-scoping and ED-008 (dedicated tenant-isolation tests).
---

Governed by: `CLAUDE.md` (tenant-scope every table via `business_id`), `docs/governance/12_Decision_Register.md`
ED-008, `docs/governance/06_Database_Design.md`.

1. **Model.** Inherit `Base`, `TimestampMixin`, and `TenantScopedMixin` from
   `backend/app/models/base.py`, exactly like `app/models/business.py` does — *except* the root
   `Business` table itself, which is not tenant-scoped (it is the tenant). `TenantScopedMixin`
   already indexes `business_id`; add further indexes for other columns you'll filter or sort by
   often.
2. **Where business_id comes from.** Never accept `business_id` from client input (body, query
   param, header). It must come from the verified-membership dependency in
   `app/security/tenant.py` (a FastAPI dependency resolved server-side from the authenticated
   Supabase session — see that file's docstring for the intended shape). Every tenant-scoped route
   depends on it.
3. **Every query is scoped.** Repository/query methods filter by `business_id` unconditionally —
   there is no "list all rows" path that skips it. When in doubt, grep the diff for a `session.query`
   or `select()` on a tenant-scoped model without a `business_id` filter nearby.
4. **Test (non-negotiable, ED-008).** Add a negative cross-tenant test under
   `backend/tests/tenant_isolation/` (see the `README.md` there) proving business A cannot read or
   write business B's row — via the API layer, not just the ORM. This is separate from an ordinary
   unit test; ED-008 requires dedicated tenant-isolation coverage.
5. **Migration.** Add an Alembic revision under `backend/migrations/versions/` with a working
   `downgrade()`, not just `upgrade()`. Table/schema-detail decisions belong with the migration
   itself, not in `docs/governance/06_Database_Design.md` (that document is intentionally high-level
   — see its Out of Scope section).
6. **Definition of done.** Model uses the mixins correctly + migration has forward and rollback +
   tenant-isolation test added and passing + no route trusts a client-supplied `business_id`.
