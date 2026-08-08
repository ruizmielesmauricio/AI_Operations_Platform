"""add parent_business_id and deleted_at to businesses

Revision ID: e1a4b7c9d2f3
Revises: d3f8a1c9e6b2
Create Date: 2026-08-08 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a4b7c9d2f3'
down_revision: Union[str, None] = 'd3f8a1c9e6b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # parent_business_id: NULL means a standalone/primary shop (what the
    # one-shop-per-account limit actually counts); non-null marks a branch
    # of that parent. Schema groundwork only in this pass — no route can
    # set this yet (the paid branch checkout flow is a deliberately
    # deferred follow-up), added now so the limit-check code and the
    # future branch feature don't need a second migration touching this
    # table. Self-referential FK, no ON DELETE CASCADE — deleting a
    # business is a soft-delete (deleted_at) in this codebase, never a
    # hard delete, so a cascade rule here would never actually fire.
    #
    # deleted_at: soft-delete marker, nullable timestamp rather than a
    # boolean — mirrors the existing nullable-timestamp-flag pattern
    # already used elsewhere in this schema (e.g.
    # import_records.reversed_at). A deleted business's rows (products,
    # sales, uploads, subscriptions, audit log, ...) are deliberately left
    # untouched — confirmed with the user: archive, not destroy.
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.add_column(sa.Column('parent_business_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            'fk_businesses_parent_business_id', 'businesses', ['parent_business_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.drop_constraint('fk_businesses_parent_business_id', type_='foreignkey')
        batch_op.drop_column('deleted_at')
        batch_op.drop_column('parent_business_id')
