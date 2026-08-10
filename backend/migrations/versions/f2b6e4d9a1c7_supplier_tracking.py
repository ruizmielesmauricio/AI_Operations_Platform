"""supplier tracking: suppliers columns, product_suppliers, inventory_movements.supplier_id

Revision ID: f2b6e4d9a1c7
Revises: a7d2e9c14f5b
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b6e4d9a1c7'
down_revision: Union[str, None] = 'a7d2e9c14f5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # suppliers existed schema-only since the initial migration
    # (name/contact_info) — this gives it its first real writer.
    with op.batch_alter_table('suppliers') as batch_op:
        batch_op.add_column(sa.Column('normalized_name', sa.String(length=255), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('status', sa.String(length=16), nullable=False, server_default='active'))
        batch_op.add_column(sa.Column('merged_into_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_suppliers_merged_into_id', 'suppliers', ['merged_into_id'], ['id'])
    op.create_index(op.f('ix_suppliers_normalized_name'), 'suppliers', ['normalized_name'], unique=False)
    # server_default was only needed to backfill existing (currently zero,
    # since suppliers has never had a writer) rows — drop it so future
    # inserts must supply a real value via the ORM, matching every other
    # non-nullable column in this schema.
    with op.batch_alter_table('suppliers') as batch_op:
        batch_op.alter_column('normalized_name', server_default=None)
        batch_op.alter_column('status', server_default=None)

    op.create_table(
        'product_suppliers',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('supplier_id', sa.Uuid(), nullable=False),
        sa.Column('supplier_sku', sa.String(length=128), nullable=True),
        sa.Column('lead_time_days', sa.DECIMAL(precision=6, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id']),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'supplier_id', name='uq_product_suppliers_product_supplier'),
    )
    op.create_index(op.f('ix_product_suppliers_business_id'), 'product_suppliers', ['business_id'], unique=False)
    op.create_index(op.f('ix_product_suppliers_product_id'), 'product_suppliers', ['product_id'], unique=False)
    op.create_index(op.f('ix_product_suppliers_supplier_id'), 'product_suppliers', ['supplier_id'], unique=False)

    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.add_column(sa.Column('supplier_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key('fk_inventory_movements_supplier_id', 'suppliers', ['supplier_id'], ['id'])
    op.create_index(op.f('ix_inventory_movements_supplier_id'), 'inventory_movements', ['supplier_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_inventory_movements_supplier_id'), table_name='inventory_movements')
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.drop_constraint('fk_inventory_movements_supplier_id', type_='foreignkey')
        batch_op.drop_column('supplier_id')

    op.drop_index(op.f('ix_product_suppliers_supplier_id'), table_name='product_suppliers')
    op.drop_index(op.f('ix_product_suppliers_product_id'), table_name='product_suppliers')
    op.drop_index(op.f('ix_product_suppliers_business_id'), table_name='product_suppliers')
    op.drop_table('product_suppliers')

    op.drop_index(op.f('ix_suppliers_normalized_name'), table_name='suppliers')
    with op.batch_alter_table('suppliers') as batch_op:
        batch_op.drop_constraint('fk_suppliers_merged_into_id', type_='foreignkey')
        batch_op.drop_column('merged_into_id')
        batch_op.drop_column('status')
        batch_op.drop_column('normalized_name')
