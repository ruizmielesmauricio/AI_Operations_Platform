"""add business logo content type

Revision ID: a7d3f1b8c4e2
Revises: f4a9c2d7e8b1
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3f1b8c4e2'
down_revision: Union[str, None] = 'f4a9c2d7e8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Doubles as the "has a logo at all" flag (NULL = none) and lets the
    # public GET .../logo route serve the right Content-Type without
    # sniffing or storing a second key/extension column — the R2 object
    # key itself is always deterministic (logos/{business_id}/logo),
    # never stored.
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.add_column(sa.Column('logo_content_type', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.drop_column('logo_content_type')
