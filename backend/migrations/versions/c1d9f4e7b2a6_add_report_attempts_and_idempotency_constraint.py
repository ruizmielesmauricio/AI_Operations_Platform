"""add attempts/last_error to reports, and its idempotency constraint

Revision ID: c1d9f4e7b2a6
Revises: 8b3e6c1a4f92
Create Date: 2026-08-07 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d9f4e7b2a6'
down_revision: Union[str, None] = '8b3e6c1a4f92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Stage D17/D18 (PR-8): attempts/last_error back the retry (PR-8.9) and
    # persistent-failure (PR-8.11) requirements — app/scheduler/tick.py's
    # reconciliation loop increments attempts and records last_error on a
    # failed generation, and stops retrying past a small cap. The unique
    # constraint is the actual mechanism behind PR-8.8's idempotency
    # ("tenant + report type + reporting period uniquely identifies one
    # report") — not just an application-layer convention.
    with op.batch_alter_table('reports') as batch_op:
        batch_op.add_column(sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('last_error', sa.String(length=1024), nullable=True))
        batch_op.create_unique_constraint(
            'uq_reports_business_id_report_type_period_start',
            ['business_id', 'report_type', 'period_start'],
        )


def downgrade() -> None:
    with op.batch_alter_table('reports') as batch_op:
        batch_op.drop_constraint('uq_reports_business_id_report_type_period_start', type_='unique')
        batch_op.drop_column('last_error')
        batch_op.drop_column('attempts')
