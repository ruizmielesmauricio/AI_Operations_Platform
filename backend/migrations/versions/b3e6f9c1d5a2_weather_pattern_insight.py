"""weather pattern insight: business lat/lon + weather_observations

Revision ID: b3e6f9c1d5a2
Revises: a7d3f1b8c4e2
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e6f9c1d5a2'
down_revision: Union[str, None] = 'a7d3f1b8c4e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, resolved lazily via the existing geocoding client when a
    # full address is present (app/geocoding/) -- degrades to NULL like
    # every other "not configured"/"not yet resolved" gap in this schema
    # rather than blocking anything. Needed so the weather feature can
    # look up a business's coordinates without re-geocoding on every
    # scheduler tick.
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.add_column(sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True))
        batch_op.add_column(sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True))

    # ORLA's own accumulating daily weather record for a business's
    # location -- one row per (business_id, observed_date), built forward
    # from whenever this ships (never backfilled synthetically). See
    # app/weather/client.py and app/application/weather_ingestion.py.
    # The unique constraint is declared inline at table-creation time
    # (not a separate create_unique_constraint call afterward) — SQLite
    # can't ALTER a constraint onto an existing table (only Postgres can),
    # and this repo's own test_schema_migrations.py runs every migration
    # against SQLite to prove they apply cleanly.
    op.create_table(
        'weather_observations',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('business_id', sa.Uuid(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False, index=True),
        sa.Column('observed_date', sa.Date(), nullable=False),
        sa.Column('rain_mm', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('temp_mean_c', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('temp_min_c', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('temp_max_c', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('wind_speed_kph', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('business_id', 'observed_date', name='uq_weather_observations_business_date'),
    )


def downgrade() -> None:
    op.drop_table('weather_observations')
    with op.batch_alter_table('businesses') as batch_op:
        batch_op.drop_column('longitude')
        batch_op.drop_column('latitude')
