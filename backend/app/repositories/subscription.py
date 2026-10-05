import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.subscription import ProcessedStripeEvent, Subscription


class SubscriptionRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_business_id(self, business_id: uuid.UUID) -> Subscription | None:
        return self.session.scalar(
            select(Subscription).where(Subscription.business_id == business_id)
        )

    def get_by_stripe_customer_id(self, stripe_customer_id: str) -> Subscription | None:
        return self.session.scalar(
            select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
        )

    def get_by_stripe_subscription_id(self, stripe_subscription_id: str) -> Subscription | None:
        return self.session.scalar(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
        )

    def create(self, business_id: uuid.UUID, stripe_customer_id: str) -> Subscription:
        subscription = Subscription(
            business_id=business_id,
            stripe_customer_id=stripe_customer_id,
            status="incomplete",
        )
        self.session.add(subscription)
        self.session.flush()
        return subscription

    def grant_complimentary(self, business_id: uuid.UUID) -> Subscription:
        """Free active access with no Stripe involvement. Never overwrites
        a real Stripe subscription (active/past_due/etc. with a Stripe
        subscription id) — that business is already paying; raising keeps
        an operator typo from silently erasing a customer's billing."""
        subscription = self.get_by_business_id(business_id)
        if subscription is not None and not subscription.is_complimentary and subscription.stripe_subscription_id:
            if subscription.status not in ("canceled", "incomplete", "incomplete_expired"):
                raise ValueError("This business already has a real Stripe subscription")
        if subscription is None:
            subscription = Subscription(business_id=business_id, stripe_customer_id=f"complimentary_{business_id}")
            self.session.add(subscription)
        elif not subscription.is_complimentary:
            # A dead/unfinished Stripe row being replaced by a complimentary one.
            subscription.stripe_customer_id = f"complimentary_{business_id}"
            subscription.stripe_subscription_id = None
        subscription.status = "active"
        subscription.is_complimentary = True
        self.session.flush()
        return subscription

    def revoke_complimentary(self, business_id: uuid.UUID) -> Subscription | None:
        subscription = self.get_by_business_id(business_id)
        if subscription is None or not subscription.is_complimentary:
            return None
        subscription.status = "canceled"
        subscription.is_complimentary = False
        self.session.flush()
        return subscription

    def upsert_from_stripe(
        self,
        *,
        business_id: uuid.UUID,
        stripe_customer_id: str,
        stripe_subscription_id: str | None = None,
        status: str | None = None,
        current_period_end: datetime | None = None,
    ) -> Subscription:
        """One row per business (enforced by a DB unique constraint), keyed
        on business_id rather than stripe_customer_id — resubscribing after
        a cancellation gets a brand new Stripe Customer, so the customer id
        alone can't tell "this business already has a row" from "this is a
        new business". Fields left as None (e.g. checkout.session.completed
        knows the customer but not yet a subscription or its status) are
        left untouched on an existing row, or default sensibly on a new one.
        """
        subscription = self.get_by_business_id(business_id)
        if subscription is None:
            subscription = Subscription(business_id=business_id, status=status or "incomplete")
            self.session.add(subscription)
        subscription.stripe_customer_id = stripe_customer_id
        # Any real Stripe event is the conversion from a complimentary
        # pilot account to a paying customer.
        subscription.is_complimentary = False
        if stripe_subscription_id is not None:
            subscription.stripe_subscription_id = stripe_subscription_id
        if status is not None:
            subscription.status = status
        if current_period_end is not None:
            subscription.current_period_end = current_period_end
        self.session.flush()
        return subscription


class ProcessedStripeEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def already_processed(self, event_id: str) -> bool:
        return (
            self.session.scalar(
                select(ProcessedStripeEvent).where(ProcessedStripeEvent.id == event_id)
            )
            is not None
        )

    def mark_processed(self, event_id: str) -> None:
        self.session.add(
            ProcessedStripeEvent(id=event_id, processed_at=datetime.now(timezone.utc))
        )
        self.session.flush()
