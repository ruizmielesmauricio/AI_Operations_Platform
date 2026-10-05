"""product_field_changes: remember what an import overwrote, so undo can revert it

Revision ID: d4a9e2c7f1b8
Revises: c8f2a5e1b9d3
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4a9e2c7f1b8'
down_revision: Union[str, None] = 'c8f2a5e1b9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'product_field_changes',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('business_id', sa.Uuid(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False, index=True),
        sa.Column('import_record_id', sa.Uuid(as_uuid=True), sa.ForeignKey('import_records.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Uuid(as_uuid=True), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('field', sa.String(length=32), nullable=False),
        sa.Column('old_value', sa.String(length=64), nullable=True),
        sa.Column('new_value', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='applied'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('product_field_changes')
