"""Free pilot access: businesses.pilot_access_until

Revision ID: d9e1f4a7c2b6
Revises: c8f2a5e1b9d3
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e1f4a7c2b6'
down_revision: Union[str, None] = 'c8f2a5e1b9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no default: every existing business stays "not a pilot".
    op.add_column('businesses', sa.Column('pilot_access_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('businesses', 'pilot_access_until')
