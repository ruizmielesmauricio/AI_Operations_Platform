"""Add ORLA session revocation boundary.

Revision ID: f4a9c2d7e8b1
Revises: a1b2c3d4e5f6
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "f4a9c2d7e8b1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("session_revoked_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("session_exception_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "session_exception_id")
    op.drop_column("users", "session_revoked_after")
