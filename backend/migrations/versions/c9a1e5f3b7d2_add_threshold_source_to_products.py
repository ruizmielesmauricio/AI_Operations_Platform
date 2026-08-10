"""add low_stock_threshold_source to products

Revision ID: c9a1e5f3b7d2
Revises: f2b6e4d9a1c7
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9a1e5f3b7d2'
down_revision: Union[str, None] = 'f2b6e4d9a1c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable — "manual" (an owner/manager typed a value) or
    # "orla_recommended" (an Accept-recommendation click, or an
    # upload-triggered recalculation applying one automatically). None
    # whenever low_stock_threshold_days itself is None (no override in
    # effect) — the two columns are always cleared/set together, see
    # app/repositories/product.py::update_low_stock_threshold_days.
    # Existing rows keep this NULL — there is no way to know, after the
    # fact, whether an existing override was ever manually typed.
    with op.batch_alter_table('products') as batch_op:
        batch_op.add_column(sa.Column('low_stock_threshold_source', sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('products') as batch_op:
        batch_op.drop_column('low_stock_threshold_source')
