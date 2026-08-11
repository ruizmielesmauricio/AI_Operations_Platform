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
        first_name: str,
        surname: str,
        email: str,
        role: str,
        user_id: str | None = None,
        address_line1: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        country: str | None = None,
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
            address_line1=address_line1,
            city=city,
            postal_code=postal_code,
            country=country,
        )
        self.session.add(seat)
        self.session.flush()
        return seat

    def get_for_business(self, seat_id: uuid.UUID, business_id: uuid.UUID) -> EmployeeSeat | None:
        return self.session.scalar(
            select(EmployeeSeat).where(EmployeeSeat.id == seat_id, EmployeeSeat.business_id == business_id)
        )

    def get_for_business_and_user(self, business_id: uuid.UUID, user_id: str) -> EmployeeSeat | None:
        # The staff self-profile route's own lookup (GET/PATCH .../me) —
        # by definition reachable only once a Membership already exists
        # for this (business_id, user_id) pair (get_current_membership),
        # and a seat only ever produces a Membership once status=="active",
        # so a row found here is always the caller's own, currently-active
        # employee profile — never a stale pending/canceled one, without
        # needing an explicit status filter.
        return self.session.scalar(
            select(EmployeeSeat).where(EmployeeSeat.business_id == business_id, EmployeeSeat.user_id == user_id)
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

    def existing_reserved_seat_for_email(self, business_id: uuid.UUID, email: str) -> EmployeeSeat | None:
        # Case-insensitive — email is conventionally case-insensitive
        # (always true for Gmail), and comparing raw case here previously
        # caused a real bug (a real account existed, but a casing
        # mismatch made it invisible to this exact check's user_id-based
        # predecessor). Prevents inviting the same person twice, rather
        # than silently creating a second seat/subscription for them.
        return self.session.scalar(
            select(EmployeeSeat).where(
                EmployeeSeat.business_id == business_id,
                func.lower(EmployeeSeat.email) == email.lower(),
                EmployeeSeat.status.in_(_RESERVED_STATUSES),
            )
        )

    def list_unlinked_pending_by_email(self, email: str) -> list[EmployeeSeat]:
        # Global, not business-scoped — reconciliation (called from
        # get_current_user_synced the moment a matching email
        # authenticates) needs every business that invited this email,
        # not just one; a person can plausibly be a pending employee at
        # more than one shop at once.
        return list(
            self.session.scalars(
                select(EmployeeSeat).where(
                    func.lower(EmployeeSeat.email) == email.lower(),
                    EmployeeSeat.user_id.is_(None),
                )
            )
        )

    def link_user(self, seat: EmployeeSeat, user_id: str) -> None:
        seat.user_id = user_id
        self.session.flush()

    def update_profile(
        self,
        seat: EmployeeSeat,
        *,
        first_name: str,
        surname: str,
        role: str,
        address_line1: str | None,
        city: str | None,
        postal_code: str | None,
        country: str | None,
    ) -> None:
        # Deliberately excludes email and status — changing email would
        # break reconciliation matching silently, and status only ever
        # changes via the payment webhook.
        seat.first_name = first_name
        seat.surname = surname
        seat.role = role
        seat.address_line1 = address_line1
        seat.city = city
        seat.postal_code = postal_code
        seat.country = country
        self.session.flush()

    def update_self_profile(
        self,
        seat: EmployeeSeat,
        *,
        first_name: str,
        surname: str,
        address_line1: str | None,
        city: str | None,
        postal_code: str | None,
        country: str | None,
    ) -> None:
        # Deliberately narrower than update_profile above: no role, no
        # status, no email — a staff member editing their own profile can
        # never touch any of those, by construction (there's no parameter
        # here to pass them through even if a caller tried).
        seat.first_name = first_name
        seat.surname = surname
        seat.address_line1 = address_line1
        seat.city = city
        seat.postal_code = postal_code
        seat.country = country
        self.session.flush()

    def set_stripe_customer_id(self, seat: EmployeeSeat, stripe_customer_id: str) -> None:
        seat.stripe_customer_id = stripe_customer_id
        self.session.flush()

    def set_status(self, seat: EmployeeSeat, status: str, *, stripe_subscription_id: str | None = None) -> None:
        seat.status = status
        if stripe_subscription_id is not None:
            seat.stripe_subscription_id = stripe_subscription_id
        self.session.flush()
