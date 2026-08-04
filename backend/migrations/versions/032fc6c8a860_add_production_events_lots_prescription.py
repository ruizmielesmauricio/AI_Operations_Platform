"""add production_events, inventory_lots, prescription_details; drop repairs

Revision ID: 032fc6c8a860
Revises: 3317575771eb
Create Date: 2026-08-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '032fc6c8a860'
down_revision: Union[str, None] = '3317575771eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # repairs/repair_parts_used (ADR-016, was "Proposed") had zero
    # references anywhere outside their own model file — confirmed unused,
    # so this is a clean drop, not a data migration. Replaced below by the
    # generalised production_events pattern.
    op.drop_index(op.f('ix_repair_parts_used_repair_id'), table_name='repair_parts_used')
    op.drop_index(op.f('ix_repair_parts_used_business_id'), table_name='repair_parts_used')
    op.drop_table('repair_parts_used')
    op.drop_index(op.f('ix_repairs_business_id'), table_name='repairs')
    op.drop_table('repairs')

    op.create_table(
        'production_events',
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=True),
        sa.Column('performed_by_id', sa.Uuid(), nullable=True),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('labour_cost', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('price_charged', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.ForeignKeyConstraint(['performed_by_id'], ['employees.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_production_events_business_id'), 'production_events', ['business_id'], unique=False)
    op.create_index(op.f('ix_production_events_event_type'), 'production_events', ['event_type'], unique=False)

    op.create_table(
        'production_event_inputs',
        sa.Column('production_event_id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('cost_price_at_time', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['production_event_id'], ['production_events.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_production_event_inputs_business_id'), 'production_event_inputs', ['business_id'], unique=False
    )
    op.create_index(
        op.f('ix_production_event_inputs_production_event_id'),
        'production_event_inputs', ['production_event_id'], unique=False,
    )

    op.create_table(
        'production_event_outputs',
        sa.Column('production_event_id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['production_event_id'], ['production_events.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_production_event_outputs_business_id'), 'production_event_outputs', ['business_id'], unique=False
    )
    op.create_index(
        op.f('ix_production_event_outputs_production_event_id'),
        'production_event_outputs', ['production_event_id'], unique=False,
    )

    op.create_table(
        'inventory_lots',
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('lot_number', sa.String(length=128), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'business_id', 'product_id', 'lot_number', name='uq_inventory_lots_business_product_lot'
        ),
    )
    op.create_index(op.f('ix_inventory_lots_business_id'), 'inventory_lots', ['business_id'], unique=False)
    op.create_index(op.f('ix_inventory_lots_product_id'), 'inventory_lots', ['product_id'], unique=False)

    # Production provenance mirrors the existing reference_id/import_record_id
    # dual-path convention (one nullable typed FK per reason); inventory_lot_id
    # is orthogonal to reason (any movement can optionally tag its lot).
    # Constraint names are shortened (not fk_<table>_<column>_<target_table>,
    # the pattern used for import_record_id) to stay under Postgres's 63-byte
    # identifier limit — the full-length names would be silently truncated.
    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.add_column(sa.Column('production_event_input_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('production_event_output_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('inventory_lot_id', sa.Uuid(), nullable=True))
        batch_op.create_index(
            op.f('ix_inventory_movements_production_event_input_id'), ['production_event_input_id'], unique=False
        )
        batch_op.create_index(
            op.f('ix_inventory_movements_production_event_output_id'), ['production_event_output_id'], unique=False
        )
        batch_op.create_index(
            op.f('ix_inventory_movements_inventory_lot_id'), ['inventory_lot_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_inv_movements_prod_event_input_id',
            'production_event_inputs', ['production_event_input_id'], ['id'],
        )
        batch_op.create_foreign_key(
            'fk_inv_movements_prod_event_output_id',
            'production_event_outputs', ['production_event_output_id'], ['id'],
        )
        batch_op.create_foreign_key(
            'fk_inv_movements_inventory_lot_id',
            'inventory_lots', ['inventory_lot_id'], ['id'],
        )

    op.create_table(
        'prescription_details',
        sa.Column('sale_item_id', sa.Uuid(), nullable=False),
        sa.Column('prescription_number', sa.String(length=128), nullable=True),
        sa.Column('prescribing_doctor', sa.String(length=255), nullable=True),
        sa.Column('controlled_substance_schedule', sa.String(length=32), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['sale_item_id'], ['sale_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sale_item_id', name='uq_prescription_details_sale_item_id'),
    )
    op.create_index(
        op.f('ix_prescription_details_business_id'), 'prescription_details', ['business_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_prescription_details_business_id'), table_name='prescription_details')
    op.drop_table('prescription_details')

    with op.batch_alter_table('inventory_movements') as batch_op:
        batch_op.drop_constraint('fk_inv_movements_inventory_lot_id', type_='foreignkey')
        batch_op.drop_constraint('fk_inv_movements_prod_event_output_id', type_='foreignkey')
        batch_op.drop_constraint('fk_inv_movements_prod_event_input_id', type_='foreignkey')
        batch_op.drop_index(op.f('ix_inventory_movements_inventory_lot_id'))
        batch_op.drop_index(op.f('ix_inventory_movements_production_event_output_id'))
        batch_op.drop_index(op.f('ix_inventory_movements_production_event_input_id'))
        batch_op.drop_column('inventory_lot_id')
        batch_op.drop_column('production_event_output_id')
        batch_op.drop_column('production_event_input_id')

    op.drop_index(op.f('ix_inventory_lots_product_id'), table_name='inventory_lots')
    op.drop_index(op.f('ix_inventory_lots_business_id'), table_name='inventory_lots')
    op.drop_table('inventory_lots')

    op.drop_index(op.f('ix_production_event_outputs_production_event_id'), table_name='production_event_outputs')
    op.drop_index(op.f('ix_production_event_outputs_business_id'), table_name='production_event_outputs')
    op.drop_table('production_event_outputs')

    op.drop_index(op.f('ix_production_event_inputs_production_event_id'), table_name='production_event_inputs')
    op.drop_index(op.f('ix_production_event_inputs_business_id'), table_name='production_event_inputs')
    op.drop_table('production_event_inputs')

    op.drop_index(op.f('ix_production_events_event_type'), table_name='production_events')
    op.drop_index(op.f('ix_production_events_business_id'), table_name='production_events')
    op.drop_table('production_events')

    # Recreate repairs/repair_parts_used exactly as the initial migration
    # left them, so the full downgrade chain to base is symmetric — the
    # initial migration's own downgrade() still expects to find and drop
    # these tables/indices.
    op.create_table(
        'repairs',
        sa.Column('customer_id', sa.Uuid(), nullable=True),
        sa.Column('mechanic_id', sa.Uuid(), nullable=True),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('labour_cost', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('price_charged', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.ForeignKeyConstraint(['mechanic_id'], ['employees.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_repairs_business_id'), 'repairs', ['business_id'], unique=False)

    op.create_table(
        'repair_parts_used',
        sa.Column('repair_id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('cost_at_time', sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['repair_id'], ['repairs.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_repair_parts_used_business_id'), 'repair_parts_used', ['business_id'], unique=False)
    op.create_index(op.f('ix_repair_parts_used_repair_id'), 'repair_parts_used', ['repair_id'], unique=False)
