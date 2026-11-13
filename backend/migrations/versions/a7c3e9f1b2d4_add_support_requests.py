"""Support handoff: support_requests (PR-5.7, ADR-028)

Revision ID: a7c3e9f1b2d4
Revises: d9e1f4a7c2b6
Create Date: 2026-11-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f1b2d4'
down_revision: Union[str, None] = 'd9e1f4a7c2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'support_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('business_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('requester_email', sa.String(length=255), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('orla_answer', sa.Text(), nullable=True),
        sa.Column('article_slugs', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('operator_notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_support_requests_business_id'), 'support_requests', ['business_id'], unique=False)
    op.create_index(op.f('ix_support_requests_user_id'), 'support_requests', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_support_requests_user_id'), table_name='support_requests')
    op.drop_index(op.f('ix_support_requests_business_id'), table_name='support_requests')
    op.drop_table('support_requests')
