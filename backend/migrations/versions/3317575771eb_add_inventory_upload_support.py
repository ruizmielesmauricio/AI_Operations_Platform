"""add inventory_movements.import_record_id and import_records.entity_type

Revision ID: 3317575771eb
Revises: 15a36bf71802
Create Date: 2026-08-04 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3317575771eb'
down_revision: Union[str, None] = '15a36bf71802'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adjustment movements (from an inventory upload) have no SaleItem to
    # hang reference_id off of, so they trace back to their ImportRecord
    # directly instead — sales movements keep using reference_id, unchanged.
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.add_column(sa.Column('import_record_id', sa.Uuid(), nullable=True))
        batch_op.create_index(
            op.f('ix_inventory_movements_import_record_id'), ['import_record_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_inventory_movements_import_record_id_import_records',
            'import_records', ['import_record_id'], ['id'],
        )

    # Denormalized from Upload.entity_type: added nullable, backfilled via a
    # portable correlated-subquery UPDATE (not "UPDATE ... FROM", which
    # SQLite doesn't support — this migration also runs against SQLite in
    # tests/integration/test_schema_migrations.py), then tightened to
    # NOT NULL. Upload.entity_type is write-once (set only at create_upload,
    # never mutated), so this backfill is exact, not a best-effort guess.
    with op.batch_alter_table('import_records') as batch_op:
        batch_op.add_column(sa.Column('entity_type', sa.String(length=32), nullable=True))

    import_records = sa.table(
        'import_records',
        sa.column('upload_id', sa.Uuid()),
        sa.column('entity_type', sa.String()),
    )
    uploads = sa.table('uploads', sa.column('id', sa.Uuid()), sa.column('entity_type', sa.String()))
    op.execute(
        import_records.update().values(
            entity_type=sa.select(uploads.c.entity_type)
            .where(uploads.c.id == import_records.c.upload_id)
            .scalar_subquery()
        )
    )

    with op.batch_alter_table('import_records') as batch_op:
        batch_op.alter_column('entity_type', nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('import_records') as batch_op:
        batch_op.drop_column('entity_type')

    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.drop_constraint(
            'fk_inventory_movements_import_record_id_import_records', type_='foreignkey'
        )
        batch_op.drop_index(op.f('ix_inventory_movements_import_record_id'))
        batch_op.drop_column('import_record_id')
