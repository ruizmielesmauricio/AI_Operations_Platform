"""add employee_seats

Revision ID: b91f4d2a7c60
Revises: f3c7b2e9a1d4
Create Date: 2026-08-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b91f4d2a7c60'
down_revision: Union[str, None] = 'f3c7b2e9a1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Paid employee seats (EUR 5/month, up to 2 per business) — mirrors a
    # branch's own dedicated-Stripe-subscription shape rather than a
    # quantity-based line item; see app/models/employee_seat.py. A row
    # here with status "pending_payment" has no matching Membership yet
    # — access is only ever granted once the webhook sees the seat's own
    # subscription reach "active".
    op.create_table(
        'employee_seats',
        sa.Column('invited_by_user_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('first_name', sa.String(length=128), nullable=False),
        sa.Column('surname', sa.String(length=128), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id']),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_subscription_id'),
    )
    op.create_index(op.f('ix_employee_seats_business_id'), 'employee_seats', ['business_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_employee_seats_business_id'), table_name='employee_seats')
    op.drop_table('employee_seats')
