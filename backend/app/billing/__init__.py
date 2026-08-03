"""Stripe integration — Checkout, webhooks, and Customer Portal (PR-7). Paid
access is only ever granted from a verified webhook, never a browser
redirect. See 11_Development_Roadmap.md, Phase 3 (Stripe test mode) and
Phase 6 (live) for rollout status.

Only client.py may import the `stripe` SDK (04_Technology_Stack.md's
payment-service boundary). service.py orchestrates; status.py is the pure
event-to-status mapping.
"""
