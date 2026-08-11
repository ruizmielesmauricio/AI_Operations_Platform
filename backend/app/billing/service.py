"""Orchestrates Checkout, the Customer Portal, and Stripe webhook processing.
Route handlers stay thin (CLAUDE.md) — this is where that logic lives, one
level above the Stripe SDK boundary in app/billing/client.py.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.application.notifications import notify_employee_payment_failed, notify_subscription_status_change
from app.billing import client
from app.billing.exceptions import EmployeeSeatPriceNotConfigured
from app.billing.status import (
    DISPUTE_EVENTS,
    HANDLED_EVENTS,
    SUBSCRIPTION_LIFECYCLE_EVENTS,
    derive_subscription_status,
)
from app.models.business import Business
from app.repositories.audit_log import record_audit_event
from app.repositories.employee_seat import EmployeeSeatRepository
from app.repositories.subscription import ProcessedStripeEventRepository, SubscriptionRepository
from app.settings.config import get_settings

logger = logging.getLogger(__name__)


def start_checkout(*, db: Session, business_id: uuid.UUID, business_email: str) -> str:
    settings = get_settings()
    # A branch (Business.parent_business_id set) checks out at the
    # discounted branch price, in its own separate Stripe subscription —
    # not a shared line item on the primary shop's subscription. This is
    # the one place that decision is made; app/billing/client.py just
    # takes whatever price_id it's given.
    business = db.get(Business, business_id)
    is_branch = business is not None and business.parent_business_id is not None
    price_id = settings.stripe_branch_price_id if is_branch else settings.stripe_price_id

    # Reuse the existing Stripe Customer on a resubscribe (e.g. after a
    # cancellation) rather than letting Checkout mint a new one each time —
    # keeps one Customer per business in Stripe, matching the one-row-per-
    # business invariant on our own subscriptions table.
    existing = SubscriptionRepository(db).get_by_business_id(business_id)
    session = client.create_checkout_session(
        business_id=business_id,
        business_email=business_email,
        price_id=price_id,
        existing_stripe_customer_id=existing.stripe_customer_id if existing else None,
        success_url=f"{settings.app_base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_base_url}/billing/cancel",
    )
    return session.url


def cancel_subscription(db: Session, *, business_id: uuid.UUID) -> bool:
    """Called from app/api/businesses.py's DELETE route when a business is
    soft-deleted — stops billing immediately rather than leaving a live
    Stripe subscription running against an archived business. A no-op,
    not an error, when the business never had a subscription at all, or
    only ever reached checkout.session.completed without a subscription
    id yet (upsert_from_stripe leaves stripe_subscription_id None until a
    customer.subscription.* event arrives) — nothing to cancel in either
    case. Updates the local row's status immediately rather than waiting
    on the customer.subscription.deleted webhook round trip: the business
    is about to disappear from every listing regardless, but keeping
    Subscription.status accurate is still worth the one extra write, and
    the webhook (once it does arrive) is idempotent via
    ProcessedStripeEventRepository, so this doesn't risk a duplicate
    state change.

    Returns whether a real Stripe subscription was actually canceled —
    the caller uses this to decide whether a "subscription_canceled"
    audit entry would be accurate or misleading (PR-6.5).
    """
    subscription = SubscriptionRepository(db).get_by_business_id(business_id)
    if subscription is None or subscription.stripe_subscription_id is None:
        return False
    client.cancel_subscription(subscription.stripe_subscription_id)
    SubscriptionRepository(db).upsert_from_stripe(
        business_id=business_id, stripe_customer_id=subscription.stripe_customer_id, status="canceled"
    )
    return True


def start_employee_seat_checkout(
    *, db: Session, business_id: uuid.UUID, employee_seat_id: uuid.UUID, business_email: str
) -> str:
    """A paid employee seat (EUR 5/month, up to 2/business) gets its own
    dedicated Stripe subscription, same shape as a branch's — just a
    distinct price and an extra `employee_seat_id` metadata key so the
    webhook (_apply_employee_seat_event below) can tell this apart from
    the business's own subscription/branch checkout.
    """
    settings = get_settings()
    if not settings.stripe_employee_seat_price_id:
        raise EmployeeSeatPriceNotConfigured()
    # Same Stripe Customer as the business's own subscription, if one
    # exists — the owner is who's actually paying for the seat.
    existing = SubscriptionRepository(db).get_by_business_id(business_id)
    session = client.create_checkout_session(
        business_id=business_id,
        business_email=business_email,
        price_id=settings.stripe_employee_seat_price_id,
        existing_stripe_customer_id=existing.stripe_customer_id if existing else None,
        success_url=f"{settings.app_base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_base_url}/billing/cancel",
        extra_metadata={"employee_seat_id": str(employee_seat_id)},
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

    if event_type in DISPUTE_EVENTS:
        # No subscription-status change: whether a dispute means anything
        # for this business is a merchant judgment call, not something to
        # automate. This at least makes it visible without a Dashboard
        # check — a real notification (email/Slack) is future work if
        # disputes turn out to be more than rare.
        logger.warning(
            "Stripe dispute created: id=%s charge=%s amount=%s reason=%s status=%s",
            obj.get("id"),
            obj.get("charge"),
            obj.get("amount"),
            obj.get("reason"),
            obj.get("status"),
        )
        return

    if event_type == "checkout.session.completed":
        business_id = uuid.UUID(obj["metadata"]["business_id"])
        employee_seat_id = obj["metadata"].get("employee_seat_id")
        if employee_seat_id:
            _apply_employee_seat_event(
                db,
                employee_seat_id=uuid.UUID(employee_seat_id),
                stripe_customer_id=obj["customer"],
                stripe_subscription_id=None,
                status=None,
            )
            return
        subscriptions.upsert_from_stripe(business_id=business_id, stripe_customer_id=obj["customer"])
        return

    if event_type in SUBSCRIPTION_LIFECYCLE_EVENTS:
        # Stripe does not guarantee delivery order, so this can arrive before
        # checkout.session.completed. subscription_data.metadata (set at
        # Checkout creation, see client.create_checkout_session) carries the
        # same business_id, so a row can still be created from this event.
        business_id = uuid.UUID(obj["metadata"]["business_id"])
        status = derive_subscription_status(event_type, obj.get("status"))
        employee_seat_id = obj["metadata"].get("employee_seat_id")
        if employee_seat_id:
            _apply_employee_seat_event(
                db,
                employee_seat_id=uuid.UUID(employee_seat_id),
                stripe_customer_id=obj["customer"],
                stripe_subscription_id=obj["id"],
                status=status,
            )
            return
        previous_status = _current_subscription_status(subscriptions, business_id)
        subscriptions.upsert_from_stripe(
            business_id=business_id,
            stripe_customer_id=obj["customer"],
            stripe_subscription_id=obj["id"],
            status=status,
            current_period_end=_subscription_period_end(obj),
        )
        _notify_business_subscription_change(db, business_id=business_id, previous_status=previous_status, new_status=status)
        return

    # invoice.paid / invoice.payment_failed. Newer Stripe API versions moved
    # the subscription reference off the invoice's top level into
    # parent.subscription_details — see 04_Technology_Stack.md for the
    # pinned API version. subscription_details.metadata mirrors
    # subscription_data.metadata for the same delivery-order reason as above.
    subscription_details = (obj.get("parent") or {}).get("subscription_details")
    if subscription_details is None:
        # A one-off invoice (invoice items billed directly, not through a
        # subscription) has no subscription_details at all. Not this
        # platform's concern — only subscription billing status matters here.
        return
    business_id = uuid.UUID(subscription_details["metadata"]["business_id"])
    status = derive_subscription_status(event_type, None)
    employee_seat_id = subscription_details["metadata"].get("employee_seat_id")
    if employee_seat_id:
        _apply_employee_seat_event(
            db,
            employee_seat_id=uuid.UUID(employee_seat_id),
            stripe_customer_id=obj["customer"],
            stripe_subscription_id=subscription_details["subscription"],
            status=status,
        )
        return
    previous_status = _current_subscription_status(subscriptions, business_id)
    subscriptions.upsert_from_stripe(
        business_id=business_id,
        stripe_customer_id=obj["customer"],
        stripe_subscription_id=subscription_details["subscription"],
        status=status,
        current_period_end=_invoice_period_end(obj),
    )
    _notify_business_subscription_change(db, business_id=business_id, previous_status=previous_status, new_status=status)


def _apply_employee_seat_event(
    db: Session,
    *,
    employee_seat_id: uuid.UUID,
    stripe_customer_id: str,
    stripe_subscription_id: str | None,
    status: str | None,
) -> None:
    """The employee-seat mirror of the business-subscription upsert above —
    same event vocabulary (derive_subscription_status), but the outcome is
    Membership existence, not a Subscription row, and "active" only ever
    happens once (idempotent): a repeated identical event must never
    create a second Membership or double-log an audit entry.
    """
    seats = EmployeeSeatRepository(db)
    seat = seats.get_by_id(employee_seat_id)
    if seat is None:
        # Defensive only — seats are never hard-deleted, so a webhook
        # naming one that isn't in our own DB should never happen in
        # practice. Must not crash the whole webhook delivery over it.
        logger.warning("Employee seat webhook event for unknown seat id=%s", employee_seat_id)
        return
    if stripe_customer_id and seat.stripe_customer_id != stripe_customer_id:
        seats.set_stripe_customer_id(seat, stripe_customer_id)
    if status is None:
        # checkout.session.completed only ever confirms the customer id —
        # the subscription's real status arrives via a separate lifecycle
        # event, possibly before this one (Stripe doesn't guarantee order).
        return

    # Local import: app/application/employee_seats.py imports this module
    # back (start_employee_seat_checkout, inside add_employee) — kept
    # local here purely to keep this file's own top-level imports free of
    # application-layer concerns; there's no actual cycle at load time
    # either way, since that other import is itself deferred to call time.
    from app.application.employee_seats import revoke_employee_membership, try_activate_employee_seat

    was_active = seat.status == "active"
    if status == "active":
        if not was_active:
            # Distinct from "employee_membership_activated" below —
            # payment can succeed well before the employee has ever
            # signed up (seat.user_id may still be None here), so
            # "payment succeeded" and "access activated" are two
            # separate, independently-timed audit events.
            record_audit_event(
                db,
                business_id=seat.business_id,
                user_id=seat.invited_by_user_id,
                action="employee_payment_succeeded",
                target_type="employee_seat",
                target_id=str(seat.id),
            )
        seats.set_status(seat, "active", stripe_subscription_id=stripe_subscription_id)
        if try_activate_employee_seat(db, seat):
            record_audit_event(
                db,
                business_id=seat.business_id,
                user_id=seat.invited_by_user_id,
                action="employee_membership_activated",
                target_type="employee_seat",
                target_id=str(seat.id),
            )
        return

    # Any non-active status (past_due, canceled, incomplete, unpaid, ...) —
    # access must not outlive payment: revoke a Membership that was
    # created while this seat was active, exactly once on the transition.
    new_status = "canceled" if status == "canceled" else "payment_failed"
    if was_active:
        revoke_employee_membership(db, seat)
    if seat.status != new_status:
        record_audit_event(
            db,
            business_id=seat.business_id,
            user_id=seat.invited_by_user_id,
            action="employee_payment_canceled" if new_status == "canceled" else "employee_payment_failed",
            target_type="employee_seat",
            target_id=str(seat.id),
            metadata={"stripe_status": status},
        )
        if new_status == "payment_failed":
            notify_employee_payment_failed(
                db, business_id=seat.business_id, seat_id=seat.id, full_name=f"{seat.first_name} {seat.surname}"
            )
    seats.set_status(seat, new_status, stripe_subscription_id=stripe_subscription_id)


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


def _current_subscription_status(subscriptions: SubscriptionRepository, business_id: uuid.UUID) -> str | None:
    """Read before upsert_from_stripe overwrites it — the only way to
    detect a real transition (e.g. active -> past_due) rather than
    notifying on every webhook delivery for a status that hasn't
    actually changed."""
    existing = subscriptions.get_by_business_id(business_id)
    return existing.status if existing is not None else None


def _notify_business_subscription_change(
    db: Session, *, business_id: uuid.UUID, previous_status: str | None, new_status: str | None
) -> None:
    """ORLA Notification Centre — Billing (main shop) / Branches (a second
    Business row with parent_business_id set, per the branch-groundwork
    schema) share this exact mechanism, since a branch is just another
    Business with its own Stripe subscription; the only difference is
    which category/wording applies, decided by parent_business_id."""
    if new_status is None or new_status == previous_status:
        return
    business = db.get(Business, business_id)
    if business is None:
        return
    notify_subscription_status_change(
        db,
        business_id=business_id,
        business_name=business.name,
        is_branch=business.parent_business_id is not None,
        new_status=new_status,
    )
