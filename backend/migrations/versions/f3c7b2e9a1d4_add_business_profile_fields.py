"""add business profile fields

Revision ID: f3c7b2e9a1d4
Revises: e1a4b7c9d2f3
Create Date: 2026-08-08 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c7b2e9a1d4'
down_revision: Union[str, None] = 'e1a4b7c9d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A per-business profile — descriptive contact/location record-keeping
    # fields only, not a new auth/login concept (confirmed with the user:
    # a branch's "manager" is a name/contact on the record, not a second
    # person who logs in — that would need an invite/permissions system
    # that doesn't exist anywhere in this codebase yet). All nullable: a
    # business is fully usable with none of this filled in, matching this
    # schema's general optional-unless-required-for-a-calculation posture.
    # timezone already exists (Business.timezone) and isn't duplicated here.
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.add_column(sa.Column('manager_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('contact_email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('contact_phone', sa.String(length=64), nullable=True))
        # A short human label distinct from the formal business name, e.g.
        # "Dublin - Rathmines" — useful once an account has more than one
        # location and the shop name alone (often identical across
        # branches) doesn't distinguish them in a list.
        batch_op.add_column(sa.Column('location_label', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('address_line1', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('city', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('postal_code', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.drop_column('country')
        batch_op.drop_column('postal_code')
        batch_op.drop_column('city')
        batch_op.drop_column('address_line1')
        batch_op.drop_column('location_label')
        batch_op.drop_column('contact_phone')
        batch_op.drop_column('contact_email')
        batch_op.drop_column('manager_name')
