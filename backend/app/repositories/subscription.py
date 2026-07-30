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

    def upsert_from_stripe(
        self,
        *,
        stripe_customer_id: str,
        stripe_subscription_id: str,
        status: str,
        current_period_end: datetime | None,
    ) -> Subscription:
        subscription = self.get_by_stripe_customer_id(stripe_customer_id)
        if subscription is None:
            raise ValueError(
                f"No subscription row for Stripe customer {stripe_customer_id}; "
                "checkout.session.completed must be processed before subscription "
                "lifecycle events."
            )
        subscription.stripe_subscription_id = stripe_subscription_id
        subscription.status = status
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
