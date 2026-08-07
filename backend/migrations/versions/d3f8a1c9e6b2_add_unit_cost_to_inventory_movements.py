"""add unit_cost to inventory_movements

Revision ID: d3f8a1c9e6b2
Revises: c1d9f4e7b2a6
Create Date: 2026-08-07 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f8a1c9e6b2'
down_revision: Union[str, None] = 'c1d9f4e7b2a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, captured only for reason="purchase" rows going forward —
    # mirrors sale_items.cost_price_at_sale's exact role (a per-transaction
    # historical cost snapshot), closing the equivalent gap on the
    # purchase side: Product.cost_price is a single "current price" value
    # silently overwritten on every re-import, so it can't answer "what
    # did we pay for this category's stock last month" for any period
    # where the price has since changed. Existing purchase rows keep this
    # NULL — no retroactive backfill is possible, the data was never
    # captured (same stated-limitation pattern as event_date's v1.19
    # backfill approximation, but here there's no approximation to fall
    # back to at all).
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.add_column(sa.Column('unit_cost', sa.DECIMAL(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.drop_column('unit_cost')
