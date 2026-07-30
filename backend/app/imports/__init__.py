"""Upload, schema detection, column-mapping confirmation, validation, and
normalisation — the "no customer-facing import template" pipeline required by
PR-2 (10_Product_Requirements.md). Everything that touches the actual data
values is deterministic code; AI may only suggest a column mapping once,
never clean, validate, or deduplicate (see the AI Boundary table in PR-2).
"""
