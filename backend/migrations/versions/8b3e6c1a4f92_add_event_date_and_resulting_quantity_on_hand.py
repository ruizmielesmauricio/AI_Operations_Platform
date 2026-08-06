"""add event_date and resulting_quantity_on_hand to inventory_movements

Revision ID: 8b3e6c1a4f92
Revises: 4f7a9d2b6e18
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b3e6c1a4f92'
down_revision: Union[str, None] = '4f7a9d2b6e18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Makes derived stock (InventoryMovementRepository.sum_by_product_ids)
    # a function of when things actually happened, not what order files
    # got uploaded/processed in — see app/models/inventory_movement.py's
    # updated docstring for the full reasoning. event_date is populated
    # going forward by every write path (app/imports/importer.py);
    # resulting_quantity_on_hand only ever by an "adjustment" (stock-count
    # reconciliation) row.
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.add_column(sa.Column('event_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('resulting_quantity_on_hand', sa.Integer(), nullable=True))

    # One-time best-effort backfill for existing rows, so historical data
    # participates in the new date-aware calculation rather than sitting
    # out of it entirely (NULL is still handled safely — "always include"
    # — but a real date is strictly better where one can be recovered).
    #
    # "sale" rows: backfilled precisely via the Sale they already
    # reference — that data has existed since the row was written, this
    # isn't a guess.
    op.execute(
        """
        UPDATE inventory_movements
        SET event_date = (
            SELECT DATE(sales.sold_at)
            FROM sale_items
            JOIN sales ON sales.id = sale_items.sale_id
            WHERE sale_items.id = inventory_movements.reference_id
        )
        WHERE reason = 'sale' AND reference_id IS NOT NULL
        """
    )
    # "purchase"/"adjustment" rows never captured a real event date before
    # this migration (purchase_date wasn't stored on the movement;
    # inventory reconciliation had no date concept at all — see aliases.py's
    # prior "no date field by design" comment, now superseded). created_at
    # is the closest available proxy — a one-time approximation for
    # pre-existing rows only; every row written from here on gets its real
    # event date from the write path, not this fallback.
    op.execute(
        """
        UPDATE inventory_movements
        SET event_date = DATE(created_at)
        WHERE reason IN ('purchase', 'adjustment')
        """
    )


def downgrade() -> None:
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.drop_column('resulting_quantity_on_hand')
        batch_op.drop_column('event_date')
