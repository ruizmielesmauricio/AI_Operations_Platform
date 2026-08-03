"""add order_reference to sales

Revision ID: ceaf0e6a05be
Revises: a7dde8211a14
Create Date: 2026-08-03 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ceaf0e6a05be'
down_revision: Union[str, None] = 'a7dde8211a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sales') as batch_op:
        batch_op.add_column(sa.Column('order_reference', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sales') as batch_op:
        batch_op.drop_column('order_reference')
