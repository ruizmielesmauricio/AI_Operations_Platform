"""add low_stock_threshold_days to products/product_categories; index alerts

Revision ID: 7e5a0c9b21f4
Revises: 032fc6c8a860
Create Date: 2026-08-04 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e5a0c9b21f4'
down_revision: Union[str, None] = '032fc6c8a860'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable on both — unset means "fall back to the next level" (product
    # -> category -> DEFAULT_LOW_STOCK_THRESHOLD_DAYS), resolved in
    # app/analytics/findings.py::resolve_low_stock_threshold, not here.
    with op.batch_alter_table('products') as batch_op:
        batch_op.add_column(sa.Column('low_stock_threshold_days', sa.DECIMAL(precision=6, scale=2), nullable=True))

    with op.batch_alter_table('product_categories') as batch_op:
        batch_op.add_column(sa.Column('low_stock_threshold_days', sa.DECIMAL(precision=6, scale=2), nullable=True))

    # Stage C12's dedup lookup (AlertRepository.get_active_by_type_and_product_ids)
    # filters on all three columns together every time it runs (once per
    # inventory-changing import/undo) — alerts previously only had an index
    # on business_id alone.
    with op.batch_alter_table('alerts') as batch_op:
        batch_op.create_index(
            op.f('ix_alerts_business_id_alert_type_status'),
            ['business_id', 'alert_type', 'status'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('alerts') as batch_op:
        batch_op.drop_index(op.f('ix_alerts_business_id_alert_type_status'))

    with op.batch_alter_table('product_categories') as batch_op:
        batch_op.drop_column('low_stock_threshold_days')

    with op.batch_alter_table('products') as batch_op:
        batch_op.drop_column('low_stock_threshold_days')
