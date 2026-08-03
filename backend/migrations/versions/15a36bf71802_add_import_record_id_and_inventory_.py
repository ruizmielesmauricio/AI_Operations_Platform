"""add import_record_id to sales and fk on inventory_movements.reference_id

Revision ID: 15a36bf71802
Revises: ceaf0e6a05be
Create Date: 2026-08-03 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15a36bf71802'
down_revision: Union[str, None] = 'ceaf0e6a05be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sales') as batch_op:
        batch_op.add_column(sa.Column('import_record_id', sa.Uuid(), nullable=True))
        batch_op.create_index(
            op.f('ix_sales_import_record_id'), ['import_record_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_sales_import_record_id_import_records', 'import_records', ['import_record_id'], ['id']
        )

    # reference_id already exists (untyped, unused by any writer) — this
    # only adds the constraint, no data migration needed.
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.create_foreign_key(
            'fk_inventory_movements_reference_id_sale_items', 'sale_items', ['reference_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.drop_constraint('fk_inventory_movements_reference_id_sale_items', type_='foreignkey')

    with op.batch_alter_table('sales') as batch_op:
        batch_op.drop_constraint('fk_sales_import_record_id_import_records', type_='foreignkey')
        batch_op.drop_index(op.f('ix_sales_import_record_id'))
        batch_op.drop_column('import_record_id')
