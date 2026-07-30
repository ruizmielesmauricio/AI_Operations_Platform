"""Pure mapping from a Stripe webhook event to the subscription status this
platform stores. No I/O, no Stripe SDK — kept separate so the mapping rules
are unit-testable on their own (ED-007) without a database or network call.
"""

SUBSCRIPTION_LIFECYCLE_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}

INVOICE_EVENTS = {"invoice.paid", "invoice.payment_failed"}

HANDLED_EVENTS = SUBSCRIPTION_LIFECYCLE_EVENTS | INVOICE_EVENTS | {"checkout.session.completed"}


def derive_subscription_status(event_type: str, subscription_payload_status: str | None) -> str:
    """`.deleted` is forced to "canceled" rather than trusting the payload's
    own status field — the event type is the more reliable signal of intent,
    and this keeps that decision in one tested place rather than assumed at
    every call site.

    invoice.paid / invoice.payment_failed describe a single invoice, not the
    subscription's own status, so they map to a fixed status instead of
    echoing anything from the payload.
    """
    if event_type == "customer.subscription.deleted":
        return "canceled"
    if event_type == "invoice.paid":
        return "active"
    if event_type == "invoice.payment_failed":
        return "past_due"
    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        if not subscription_payload_status:
            raise ValueError(f"{event_type} payload is missing a subscription status")
        return subscription_payload_status
    raise ValueError(f"No status mapping for event type: {event_type}")
