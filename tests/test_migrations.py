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
            self.addCleanup(engine.dispose)

            apply_migrations(engine)

            inspector = inspect(engine)
            self.assertIn("analysis_snapshots", inspector.get_table_names())
            self.assertIn("telegram_subscriptions", inspector.get_table_names())
            self.assertIn("instrument_registry", inspector.get_table_names())
            self.assertIn("provider_registry", inspector.get_table_names())
            self.assertIn("source_snapshots", inspector.get_table_names())
            self.assertIn("schema_migrations", inspector.get_table_names())
            telegram_columns = {column["name"] for column in inspector.get_columns("telegram_subscriptions")}
            self.assertIn("quiet_hours_start_minute", telegram_columns)
            self.assertIn("max_alerts_per_day", telegram_columns)
            self.assertIn("market_hours_only", telegram_columns)
            self.assertIn("min_confidence", telegram_columns)
            self.assertIn("last_digest_fingerprint", telegram_columns)
            self.assertIn("language", telegram_columns)

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
                    "0006_telegram_preferences",
                    "0007_runtime_budget_counters",
                    "0008_telegram_min_confidence",
                    "0009_telegram_alert_deduplication",
                    "0010_telegram_alert_rules",
                    "0011_telegram_holdings",
                    "0012_timezone_and_jobs",
                    "0013_usage_metrics",
                    "0014_telegram_language",
                ],
            )
            self.assertIn("alert_rules", telegram_columns)
            self.assertIn("holdings", telegram_columns)
            self.assertIn("timezone", telegram_columns)
            self.assertIn("scheduled_jobs", inspector.get_table_names())
            self.assertIn("usage_metrics", inspector.get_table_names())

    def test_apply_migrations_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "migrations.db"
            engine = create_engine(f"sqlite:///{db_path}")
            self.addCleanup(engine.dispose)

            apply_migrations(engine)
            apply_migrations(engine)

            with engine.connect() as connection:
                revision_count = connection.execute(
                    text("SELECT COUNT(*) FROM schema_migrations")
                ).scalar_one()

            self.assertEqual(revision_count, 14)

    def test_init_db_uses_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "init.db"
            engine = create_engine(f"sqlite:///{db_path}")
            self.addCleanup(engine.dispose)

            from app import database as database_module

            original_engine = database_module.engine
            try:
                database_module.engine = engine
                init_db()
            finally:
                database_module.engine = original_engine

            inspector = inspect(engine)
            self.assertIn("schema_migrations", inspector.get_table_names())
