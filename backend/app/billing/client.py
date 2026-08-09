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
    *,
    business_id: uuid.UUID,
    business_email: str,
    success_url: str,
    cancel_url: str,
    price_id: str,
    existing_stripe_customer_id: str | None = None,
    # Merged into both metadata dicts alongside business_id — the one
    # extension point every other Checkout use case (employee seats,
    # PR-6.5-adjacent) needs: a second identifier the webhook can key off
    # of instead of business_id alone, without this function needing to
    # know what any of them mean. See app/billing/service.py::_apply_event.
    extra_metadata: dict[str, str] | None = None,
) -> stripe.checkout.Session:
    # price_id is a required, explicit param, not defaulted to
    # settings.stripe_price_id here — app/billing/service.py::
    # start_checkout is the one place that decides primary vs branch
    # price, so this stays a plain pass-through rather than duplicating
    # that decision.
    #
    # Reuse the business's existing Stripe Customer (e.g. resubscribing
    # after a cancellation) rather than customer_email, which would mint a
    # new Customer object every time.
    customer_kwargs = (
        {"customer": existing_stripe_customer_id}
        if existing_stripe_customer_id
        else {"customer_email": business_email}
    )
    metadata = {"business_id": str(business_id), **(extra_metadata or {})}
    return _client().checkout.Session.create(
        mode="subscription",
        # No payment_method_types: Stripe shows whichever methods are
        # enabled for this account in the Dashboard and eligible for the
        # customer, rather than a fixed list baked into the integration.
        line_items=[{"price": price_id, "quantity": 1}],
        automatic_tax={"enabled": True},
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
        subscription_data={"metadata": metadata},
        **customer_kwargs,
    )


def create_billing_portal_session(
    *, stripe_customer_id: str, return_url: str
) -> stripe.billing_portal.Session:
    return _client().billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )


def cancel_subscription(stripe_subscription_id: str) -> stripe.Subscription:
    """Immediate cancellation (Stripe's DELETE /v1/subscriptions/:id), not
    cancel_at_period_end — a deleted business (app/repositories/business.py::
    soft_delete_business) is being archived right now, not just having its
    billing wound down while the shop stays usable, so a grace period until
    the end of the current billing cycle doesn't match the action being
    taken. `stripe.Subscription.delete(id)` (not `.cancel()`) is the
    class-method-callable form the Stripe SDK dispatches to when called
    with a plain id string rather than an instance — the same
    call-with-an-id-directly shape as every other function in this file,
    no separate retrieve-then-cancel round trip needed."""
    return _client().Subscription.delete(stripe_subscription_id)


def construct_webhook_event(payload: bytes, signature_header: str) -> dict:
    settings = get_settings()
    try:
        event = stripe.Webhook.construct_event(
            payload, signature_header, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError as exc:
        raise InvalidWebhookSignature(str(exc)) from exc
    return event.to_dict()
