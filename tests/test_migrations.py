from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine, inspect, text

from app.database import init_db
from app.migrations import apply_migrations


class MigrationTests(unittest.TestCase):
    def test_apply_migrations_creates_baseline_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "migrations.db"
            engine = create_engine(f"sqlite:///{db_path}")

            apply_migrations(engine)

            inspector = inspect(engine)
            self.assertIn("analysis_snapshots", inspector.get_table_names())
            self.assertIn("telegram_subscriptions", inspector.get_table_names())
            self.assertIn("instrument_registry", inspector.get_table_names())
            self.assertIn("provider_registry", inspector.get_table_names())
            self.assertIn("source_snapshots", inspector.get_table_names())
            self.assertIn("schema_migrations", inspector.get_table_names())

            with engine.connect() as connection:
                revisions = connection.execute(
                    text("SELECT revision FROM schema_migrations ORDER BY revision")
                ).fetchall()

            self.assertEqual(
                [row[0] for row in revisions],
                [
                    "0001_initial_schema",
                    "0002_instrument_registry",
                    "0003_provider_registry",
                    "0004_source_snapshots",
                    "0005_telegram_watchlists",
                ],
            )

    def test_apply_migrations_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "migrations.db"
            engine = create_engine(f"sqlite:///{db_path}")

            apply_migrations(engine)
            apply_migrations(engine)

            with engine.connect() as connection:
                revision_count = connection.execute(
                    text("SELECT COUNT(*) FROM schema_migrations")
                ).scalar_one()

            self.assertEqual(revision_count, 5)

    def test_init_db_uses_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "init.db"
            engine = create_engine(f"sqlite:///{db_path}")

            from app import database as database_module

            original_engine = database_module.engine
            try:
                database_module.engine = engine
                init_db()
            finally:
                database_module.engine = original_engine

            inspector = inspect(engine)
            self.assertIn("schema_migrations", inspector.get_table_names())
