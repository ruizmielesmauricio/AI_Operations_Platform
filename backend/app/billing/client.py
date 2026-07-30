"""The only module allowed to import the `stripe` SDK — the narrow
payment-service boundary described in 04_Technology_Stack.md, so swapping
providers later never means hunting through business logic for a vendor
call. Every other file in app/billing/ (and everything outside it) goes
through the functions here.
"""

import uuid

import stripe

from app.billing.exceptions import InvalidWebhookSignature
from app.settings.config import get_settings


def _client():
    stripe.api_key = get_settings().stripe_secret_key
    return stripe


def create_checkout_session(
    *, business_id: uuid.UUID, business_email: str, success_url: str, cancel_url: str
) -> stripe.checkout.Session:
    settings = get_settings()
    return _client().checkout.Session.create(
        mode="subscription",
        payment_method_types=["card", "sepa_debit"],
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        customer_email=business_email,
        automatic_tax={"enabled": True},
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"business_id": str(business_id)},
        subscription_data={"metadata": {"business_id": str(business_id)}},
    )


def create_billing_portal_session(
    *, stripe_customer_id: str, return_url: str
) -> stripe.billing_portal.Session:
    return _client().billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )


def construct_webhook_event(payload: bytes, signature_header: str) -> stripe.Event:
    settings = get_settings()
    try:
        return stripe.Webhook.construct_event(
            payload, signature_header, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError as exc:
        raise InvalidWebhookSignature(str(exc)) from exc
