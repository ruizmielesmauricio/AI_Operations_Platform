"""add purchase_reference, repair_reference, and dedup lookup indexes

Revision ID: 4f7a9d2b6e18
Revises: 9c2e5f7a1b3d
Create Date: 2026-08-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f7a9d2b6e18'
down_revision: Union[str, None] = '9c2e5f7a1b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cross-upload duplicate detection (a shop re-uploading an overlapping
    # export must not silently double-count revenue/stock/repairs) — see
    # app/imports/importer.py's list_existing_*_references methods, which
    # this index exists to serve.
    with op.batch_alter_table('sales') as batch_op:
        batch_op.create_index(
            op.f('ix_sales_business_id_order_reference'), ['business_id', 'order_reference'], unique=False
        )

    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.add_column(sa.Column('purchase_reference', sa.String(length=255), nullable=True))
        batch_op.create_index(
            op.f('ix_inventory_movements_business_id_purchase_reference'),
            ['business_id', 'purchase_reference'],
            unique=False,
        )

    with op.batch_alter_table('production_events') as batch_op:
        batch_op.add_column(sa.Column('repair_reference', sa.String(length=255), nullable=True))
        batch_op.create_index(
            op.f('ix_production_events_business_id_repair_reference'),
            ['business_id', 'repair_reference'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('production_events') as batch_op:
        batch_op.drop_index(op.f('ix_production_events_business_id_repair_reference'))
        batch_op.drop_column('repair_reference')

    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.drop_index(op.f('ix_inventory_movements_business_id_purchase_reference'))
        batch_op.drop_column('purchase_reference')

    with op.batch_alter_table('sales') as batch_op:
        batch_op.drop_index(op.f('ix_sales_business_id_order_reference'))
