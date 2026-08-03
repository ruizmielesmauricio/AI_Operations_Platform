"""enforce one subscription per business

Revision ID: 424224e69ec2
Revises: a70aac55ced8
Create Date: 2026-08-03 13:08:38.093169

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '424224e69ec2'
down_revision: Union[str, None] = 'a70aac55ced8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table rather than a direct ALTER TABLE: SQLite (used by
    # the test suite, see tests/integration/test_schema_migrations.py) can't
    # ALTER a constraint onto an existing table directly, only via
    # copy-and-swap. Alembic picks the right strategy per dialect either way
    # — a plain ALTER on Postgres, batch mode only on SQLite.
    with op.batch_alter_table('subscriptions') as batch_op:
        batch_op.create_unique_constraint('uq_subscriptions_business_id', ['business_id'])
        batch_op.create_foreign_key(
            'fk_subscriptions_business_id_businesses', 'businesses', ['business_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('subscriptions') as batch_op:
        batch_op.drop_constraint('fk_subscriptions_business_id_businesses', type_='foreignkey')
        batch_op.drop_constraint('uq_subscriptions_business_id', type_='unique')
