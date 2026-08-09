import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee_seat import EmployeeSeat

# A seat counts against the max-2-per-business cap the moment it's
# created (pending_payment), not only once paid — otherwise nothing stops
# an owner from spamming unlimited pending invites past the real cap.
_RESERVED_STATUSES = ("pending_payment", "active")


class EmployeeSeatRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        invited_by_user_id: str,
        user_id: str,
        first_name: str,
        surname: str,
        email: str,
        role: str,
    ) -> EmployeeSeat:
        seat = EmployeeSeat(
            business_id=business_id,
            invited_by_user_id=invited_by_user_id,
            user_id=user_id,
            first_name=first_name,
            surname=surname,
            email=email,
            role=role,
            status="pending_payment",
        )
        self.session.add(seat)
        self.session.flush()
        return seat

    def get_for_business(self, seat_id: uuid.UUID, business_id: uuid.UUID) -> EmployeeSeat | None:
        return self.session.scalar(
            select(EmployeeSeat).where(EmployeeSeat.id == seat_id, EmployeeSeat.business_id == business_id)
        )

    def get_by_id(self, seat_id: uuid.UUID) -> EmployeeSeat | None:
        # Not business-scoped — used only from the webhook handler
        # (app/billing/service.py), which trusts Stripe's own
        # signature-verified metadata for which seat an event is about,
        # the same trust level SubscriptionRepository.get_by_business_id
        # already gets from that same metadata for the business path.
        return self.session.get(EmployeeSeat, seat_id)

    def list_for_business(self, business_id: uuid.UUID) -> list[EmployeeSeat]:
        return list(
            self.session.scalars(
                select(EmployeeSeat)
                .where(EmployeeSeat.business_id == business_id)
                .order_by(EmployeeSeat.created_at.desc())
            )
        )

    def count_reserved_for_business(self, business_id: uuid.UUID) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(EmployeeSeat)
                .where(EmployeeSeat.business_id == business_id, EmployeeSeat.status.in_(_RESERVED_STATUSES))
            )
            or 0
        )

    def existing_reserved_seat_for_user(self, business_id: uuid.UUID, user_id: str) -> EmployeeSeat | None:
        # Prevents inviting the same already-a-member (or already-invited)
        # person twice, rather than silently creating a second seat/
        # subscription for one person.
        return self.session.scalar(
            select(EmployeeSeat).where(
                EmployeeSeat.business_id == business_id,
                EmployeeSeat.user_id == user_id,
                EmployeeSeat.status.in_(_RESERVED_STATUSES),
            )
        )

    def set_stripe_customer_id(self, seat: EmployeeSeat, stripe_customer_id: str) -> None:
        seat.stripe_customer_id = stripe_customer_id
        self.session.flush()

    def set_status(self, seat: EmployeeSeat, status: str, *, stripe_subscription_id: str | None = None) -> None:
        seat.status = status
        if stripe_subscription_id is not None:
            seat.stripe_subscription_id = stripe_subscription_id
        self.session.flush()
