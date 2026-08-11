"""add notifications table

Revision ID: a1b2c3d4e5f6
Revises: c9a1e5f3b7d2
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c9a1e5f3b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('business_id', sa.Uuid(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('type_key', sa.String(length=64), nullable=False),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('action_label', sa.String(length=64), nullable=True),
        sa.Column('action_url', sa.String(length=255), nullable=True),
        sa.Column('related_entity_type', sa.String(length=32), nullable=True),
        sa.Column('related_entity_id', sa.Uuid(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='unread'),
        sa.Column('visible_to_role', sa.String(length=16), nullable=True),
        sa.Column('dedup_key', sa.String(length=128), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_notifications_business_id', 'notifications', ['business_id'])
    op.create_index('ix_notifications_dedup_key', 'notifications', ['dedup_key'])
    # Read/list is always "this business, newest first, optionally filtered
    # to unread" — the one query every list + unread-count call makes.
    op.create_index('ix_notifications_business_status', 'notifications', ['business_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_notifications_business_status', table_name='notifications')
    op.drop_index('ix_notifications_dedup_key', table_name='notifications')
    op.drop_index('ix_notifications_business_id', table_name='notifications')
    op.drop_table('notifications')
