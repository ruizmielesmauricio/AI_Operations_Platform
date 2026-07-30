"""Tenant resolution and enforcement.

Per PR-6.2 (10_Product_Requirements.md), business_id is never trusted from the
browser. This module will resolve the authenticated Supabase session to a
verified business membership server-side, and expose that as a FastAPI
dependency every tenant-scoped route requires. Implemented alongside Supabase
Auth wiring (roadmap Phase 2, "Authentication" / "Tenant isolation").
"""
