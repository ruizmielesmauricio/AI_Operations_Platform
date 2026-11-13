# ADR-025: Free pilot access as an operator-granted time window on the business, not a Stripe coupon or a self-service switch

**Status:** Accepted (implemented)
**Date:** 2026-11-12
**Related:** BD-008, `backend/app/billing/pilot.py`, `backend/app/billing/access.py`, `backend/app/application/pilot_access.py`, `backend/scripts/pilot_access.py`, migration `d9e1f4a7c2b6`, Jira ORLA-77

## Context

BD-008: pilot testers will not pay. Until now every value-creating route (uploads, imports, PDF invoices) required an active Stripe subscription (`require_active_subscription`), and branches (€30, BD-007) and staff seats (€5) always went through Stripe Checkout. Pilots therefore had no way in without a card.

## Decision

- `Business.pilot_access_until` (nullable timestamp). A business has access when its Stripe subscription is active **or** `pilot_access_until` is in the future. A paid subscription wins when both apply.
- One shared check, `app/billing/pilot.py::pilot_access_active`, dependency-free so any layer can use it without import cycles. `app/billing/access.py::business_access` returns `"subscription" | "pilot" | None`, and `require_active_subscription` uses it.
- **Operator-only.** Granted, ended and listed with `scripts/pilot_access.py` (`grant --email|--business-id --days N`, `end`, `list`), backed by `app/application/pilot_access.py`. There is deliberately **no HTTP route**: a business-facing endpoint would let any owner give themselves free access. Pilot length is capped at 366 days.
- A grant covers the business and all its existing branches. A branch created during a pilot inherits the window; a staff seat added during a pilot is activated without checkout (it still waits for the person to sign in).
- Every grant, end, inherited branch and free seat is written to the audit log; the owner gets a Billing notification when a pilot starts and ends.
- `GET /billing/subscription` returns `access` and `pilot_access_until`; the frontend gates on `access`, not on the Stripe status, and shows "Free pilot until <date>" / "Pilot ended".
- The scheduler's data-freshness and AI-health checks include pilot businesses.

## Consequences

- Pilots can use the whole product without payment details; when a pilot ends, data is kept and uploads need a subscription again.
- Pilot status is invisible to Stripe, so revenue reporting stays clean.
- Granting requires shell access to the backend. Acceptable for 3–5 pilots; a protected operator UI may be needed later.

## Alternatives Considered

- **100% Stripe coupons / trial periods:** still require a card at checkout and couple pilot logic to Stripe objects (and BD-007/€5 seats would each need their own coupons). Rejected.
- **An owner-facing "I'm a pilot" switch or code:** guessable or shareable; rejected for security.
- **A boolean `is_pilot` flag:** no built-in end; an end date lets a pilot expire on its own.

## Review Trigger

More than ~10 concurrent pilots (an operator UI becomes worth building), or a decision to charge pilots (would supersede BD-008).
