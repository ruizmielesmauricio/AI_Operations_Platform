"""Orchestrates Checkout, the Customer Portal, and Stripe webhook processing.
Route handlers stay thin (CLAUDE.md) — this is where that logic lives, one
level above the Stripe SDK boundary in app/billing/client.py.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.billing import client
from app.billing.status import HANDLED_EVENTS, SUBSCRIPTION_LIFECYCLE_EVENTS, derive_subscription_status
from app.repositories.subscription import ProcessedStripeEventRepository, SubscriptionRepository
from app.settings.config import get_settings


def start_checkout(*, business_id: uuid.UUID, business_email: str) -> str:
    settings = get_settings()
    session = client.create_checkout_session(
        business_id=business_id,
        business_email=business_email,
        success_url=f"{settings.app_base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_base_url}/billing/cancel",
    )
    return session.url


def start_portal_session(*, stripe_customer_id: str) -> str:
    settings = get_settings()
    session = client.create_billing_portal_session(
        stripe_customer_id=stripe_customer_id,
        return_url=f"{settings.app_base_url}/settings/billing",
    )
    return session.url


def handle_webhook_event(db: Session, payload: bytes, signature_header: str) -> None:
    event = client.construct_webhook_event(payload, signature_header)
    event_id = event["id"]
    event_type = event["type"]

    processed_events = ProcessedStripeEventRepository(db)
    if processed_events.already_processed(event_id):
        return

    if event_type in HANDLED_EVENTS:
        _apply_event(db, event_type, event["data"]["object"])

    processed_events.mark_processed(event_id)
    db.commit()


def _apply_event(db: Session, event_type: str, obj: dict) -> None:
    subscriptions = SubscriptionRepository(db)

    if event_type == "checkout.session.completed":
        business_id = uuid.UUID(obj["metadata"]["business_id"])
        if subscriptions.get_by_stripe_customer_id(obj["customer"]) is None:
            subscriptions.create(business_id=business_id, stripe_customer_id=obj["customer"])
        return

    if event_type in SUBSCRIPTION_LIFECYCLE_EVENTS:
        status = derive_subscription_status(event_type, obj.get("status"))
        subscriptions.upsert_from_stripe(
            stripe_customer_id=obj["customer"],
            stripe_subscription_id=obj["id"],
            status=status,
            current_period_end=_subscription_period_end(obj),
        )
        return

    # invoice.paid / invoice.payment_failed
    status = derive_subscription_status(event_type, None)
    subscriptions.upsert_from_stripe(
        stripe_customer_id=obj["customer"],
        stripe_subscription_id=obj["subscription"],
        status=status,
        current_period_end=_invoice_period_end(obj),
    )


def _subscription_period_end(subscription_object: dict) -> datetime | None:
    # Stripe moved current_period_end from the subscription to its line
    # items in newer API versions; try the item location first and fall
    # back to the old top-level field for older API versions/fixtures.
    items = subscription_object.get("items", {}).get("data", [])
    ts = items[0].get("current_period_end") if items else None
    if ts is None:
        ts = subscription_object.get("current_period_end")
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def _invoice_period_end(invoice_object: dict) -> datetime | None:
    lines = invoice_object.get("lines", {}).get("data", [])
    ts = lines[0].get("period", {}).get("end") if lines else None
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
