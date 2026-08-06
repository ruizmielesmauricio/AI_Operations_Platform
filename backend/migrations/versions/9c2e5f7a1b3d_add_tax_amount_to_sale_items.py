"""add tax_amount to sale_items

Revision ID: 9c2e5f7a1b3d
Revises: 762b85f9fb2d
Create Date: 2026-08-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c2e5f7a1b3d'
down_revision: Union[str, None] = '762b85f9fb2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, mirrors cost_price_at_sale exactly — captured at import
    # time from an optional Tax/VAT column so gross margin can be computed
    # net of tax when known, instead of assuming a sale's total is
    # tax-exclusive (see app/analytics/financial.py's net_gross_margin_pct).
    with op.batch_alter_table('sale_items') as batch_op:
        batch_op.add_column(sa.Column('tax_amount', sa.DECIMAL(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sale_items') as batch_op:
        batch_op.drop_column('tax_amount')
