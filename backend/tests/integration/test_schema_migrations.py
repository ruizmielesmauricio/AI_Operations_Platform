import os
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.models import Base

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_migrations_apply_cleanly_and_match_models():
    """Runs the real Alembic migration chain against a throwaway database
    and asserts every table in the SQLAlchemy models actually gets created.
    Uses SQLite as a stand-in dialect — safe because every model uses only
    cross-dialect column types (see PKMixin/TenantScopedMixin in
    app/models/base.py) — so this runs without a live Postgres server while
    still proving the migration chain itself is correct.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "migration_test.db")
        database_url = f"sqlite:///{db_path}"

        config = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
        config.set_main_option("script_location", os.path.join(BACKEND_ROOT, "migrations"))
        config.set_main_option("sqlalchemy.url", database_url)

        command.upgrade(config, "head")

        engine = create_engine(database_url)
        actual_tables = set(inspect(engine).get_table_names())
        expected_tables = set(Base.metadata.tables.keys())

        assert expected_tables.issubset(actual_tables), (
            f"Migration did not create all model tables. Missing: {expected_tables - actual_tables}"
        )

        command.downgrade(config, "base")
        remaining = set(inspect(engine).get_table_names()) & expected_tables
        assert not remaining, f"Downgrade did not remove tables: {remaining}"
