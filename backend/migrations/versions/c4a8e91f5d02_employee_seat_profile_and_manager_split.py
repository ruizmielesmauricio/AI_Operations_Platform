"""employee seat profile fields, nullable user_id, business manager name split

Revision ID: c4a8e91f5d02
Revises: b91f4d2a7c60
Create Date: 2026-08-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a8e91f5d02'
down_revision: Union[str, None] = 'b91f4d2a7c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Product direction: owner/admin creates the employee profile directly
    # — the employee no longer needs an existing account first. user_id is
    # now nullable, linked automatically the first time that email
    # authenticates (app/application/employee_seats.py::
    # reconcile_pending_employee_seats).
    with op.batch_alter_table('employee_seats') as batch_op:
        batch_op.alter_column('user_id', existing_type=sa.String(length=64), nullable=True)
        batch_op.add_column(sa.Column('address_line1', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('city', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('postal_code', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=128), nullable=True))

    # Owner/manager name split into first/surname (not one combined
    # field, direct request). Best-effort backfill: split any existing
    # value on its first space — "Siobhan Murphy" -> "Siobhan"/"Murphy",
    # a single-word value (e.g. "Mauricio") lands entirely in first_name
    # with surname left NULL, which is honest (there's no way to guess a
    # missing surname) rather than a fabricated split.
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.add_column(sa.Column('manager_first_name', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('manager_surname', sa.String(length=128), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, manager_name FROM businesses WHERE manager_name IS NOT NULL")
    ).fetchall()
    for row in rows:
        parts = row.manager_name.strip().split(" ", 1)
        first_name = parts[0] or None
        surname = parts[1] if len(parts) > 1 and parts[1] else None
        connection.execute(
            sa.text("UPDATE businesses SET manager_first_name = :first, manager_surname = :surname WHERE id = :id"),
            {"first": first_name, "surname": surname, "id": row.id},
        )

    with op.batch_alter_table('businesses') as batch_op:
        batch_op.drop_column('manager_name')


def downgrade() -> None:
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.add_column(sa.Column('manager_name', sa.String(length=255), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, manager_first_name, manager_surname FROM businesses WHERE manager_first_name IS NOT NULL")
    ).fetchall()
    for row in rows:
        combined = row.manager_first_name if not row.manager_surname else f"{row.manager_first_name} {row.manager_surname}"
        connection.execute(
            sa.text("UPDATE businesses SET manager_name = :combined WHERE id = :id"),
            {"combined": combined, "id": row.id},
        )

    with op.batch_alter_table('businesses') as batch_op:
        batch_op.drop_column('manager_surname')
        batch_op.drop_column('manager_first_name')

    with op.batch_alter_table('employee_seats') as batch_op:
        batch_op.drop_column('country')
        batch_op.drop_column('postal_code')
        batch_op.drop_column('city')
        batch_op.drop_column('address_line1')
        batch_op.alter_column('user_id', existing_type=sa.String(length=64), nullable=False)
