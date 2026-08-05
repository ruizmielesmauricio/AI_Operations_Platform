"""add import_record_id to production_events

Revision ID: 762b85f9fb2d
Revises: 7e5a0c9b21f4
Create Date: 2026-08-05 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '762b85f9fb2d'
down_revision: Union[str, None] = '7e5a0c9b21f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lets a "repairs" import be undo-tracked the same way sales/inventory/
    # purchases already are (bulk-delete by import_record_id) — mirrors
    # Sale.import_record_id's exact shape.
    with op.batch_alter_table('production_events') as batch_op:
        batch_op.add_column(sa.Column('import_record_id', sa.Uuid(), nullable=True))
        batch_op.create_index(
            op.f('ix_production_events_import_record_id'), ['import_record_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_production_events_import_record_id',
            'import_records', ['import_record_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('production_events') as batch_op:
        batch_op.drop_constraint('fk_production_events_import_record_id', type_='foreignkey')
        batch_op.drop_index(op.f('ix_production_events_import_record_id'))
        batch_op.drop_column('import_record_id')
