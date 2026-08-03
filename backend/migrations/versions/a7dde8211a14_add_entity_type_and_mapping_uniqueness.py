"""add entity_type to uploads and uniqueness to import_mapping_profiles

Revision ID: a7dde8211a14
Revises: 424224e69ec2
Create Date: 2026-08-03 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7dde8211a14'
down_revision: Union[str, None] = '424224e69ec2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default backfills existing rows ("sales" is the only entity
    # type that has ever existed), then gets dropped so the column has no
    # implicit default going forward — every new Upload must state its
    # entity_type explicitly via the API.
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.add_column(
            sa.Column('entity_type', sa.String(length=32), nullable=False, server_default='sales')
        )
        batch_op.alter_column('entity_type', server_default=None)

    # Without this, two ImportMappingProfile rows could exist for the same
    # (business_id, source_signature), making "reuse the saved mapping"
    # ambiguous about which one to pick (PR-2.5).
    with op.batch_alter_table('import_mapping_profiles') as batch_op:
        batch_op.create_unique_constraint(
            'uq_import_mapping_profiles_business_signature', ['business_id', 'source_signature']
        )


def downgrade() -> None:
    with op.batch_alter_table('import_mapping_profiles') as batch_op:
        batch_op.drop_constraint('uq_import_mapping_profiles_business_signature', type_='unique')
    with op.batch_alter_table('uploads') as batch_op:
        batch_op.drop_column('entity_type')
