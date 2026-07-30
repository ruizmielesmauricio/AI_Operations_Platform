"""Database access layer.

Per CLAUDE.md, route handlers stay thin and never issue queries directly —
every query lives behind a repository. Tenant-scoped repositories must filter
by business_id here, not trust it from the caller (see app/security/tenant.py).
"""
