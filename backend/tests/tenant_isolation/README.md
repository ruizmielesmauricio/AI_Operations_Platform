# Tenant isolation tests

Kept in its own directory, separate from general integration tests, per
PR-6.1: "Enforce tenant isolation on every request — integration tests prove
cross-tenant access fails." Every tenant-scoped route and repository method
gets a test here proving business A can never read or write business B's
data. This is a Phase 2 gate item (11_Development_Roadmap.md, Gate B) — not
optional, not deferred.
