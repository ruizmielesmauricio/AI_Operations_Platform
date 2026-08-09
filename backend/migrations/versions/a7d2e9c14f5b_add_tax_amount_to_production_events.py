"""add tax_amount to production_events

Revision ID: a7d2e9c14f5b
Revises: c4a8e91f5d02
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d2e9c14f5b'
down_revision: Union[str, None] = 'c4a8e91f5d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, mirrors sale_items.tax_amount's exact role — only
    # meaningful for event_type="repair" rows where price_charged is a
    # tax-inclusive invoice total. Existing rows keep this NULL; no
    # retroactive backfill is possible (the data was never captured).
    with op.batch_alter_table('production_events') as batch_op:
        batch_op.add_column(sa.Column('tax_amount', sa.DECIMAL(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('production_events') as batch_op:
        batch_op.drop_column('tax_amount')
