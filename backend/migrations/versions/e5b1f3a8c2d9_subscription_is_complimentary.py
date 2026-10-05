"""subscriptions.is_complimentary: free pilot/tester accounts without Stripe

Revision ID: e5b1f3a8c2d9
Revises: d4a9e2c7f1b8
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b1f3a8c2d9'
down_revision: Union[str, None] = 'd4a9e2c7f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('subscriptions') as batch_op:
        batch_op.add_column(sa.Column('is_complimentary', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('subscriptions') as batch_op:
        batch_op.drop_column('is_complimentary')
