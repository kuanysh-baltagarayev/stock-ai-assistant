from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, String, Table, Column, insert, select, text
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

from app.database import Base


MIGRATION_METADATA = MetaData()
SCHEMA_MIGRATIONS = Table(
    "schema_migrations",
    MIGRATION_METADATA,
    Column("revision", String(64), primary_key=True),
    Column("description", String(255), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class Migration:
    revision: str
    description: str
    upgrade: Callable[[Connection], None]


def _upgrade_0001_initial_schema(connection: Connection) -> None:
    import app.models  # noqa: F401 - registers SQLAlchemy models before create_all

    Base.metadata.create_all(bind=connection)


def _upgrade_0002_instrument_registry(connection: Connection) -> None:
    import app.models  # noqa: F401 - registers SQLAlchemy models before create_all

    Base.metadata.create_all(bind=connection, tables=[app.models.InstrumentRegistry.__table__])


def _upgrade_0003_provider_registry(connection: Connection) -> None:
    import app.models  # noqa: F401 - registers SQLAlchemy models before create_all

    Base.metadata.create_all(bind=connection, tables=[app.models.ProviderRegistry.__table__])


def _upgrade_0004_source_snapshots(connection: Connection) -> None:
    import app.models  # noqa: F401 - registers SQLAlchemy models before create_all

    Base.metadata.create_all(bind=connection, tables=[app.models.SourceSnapshot.__table__])


def _upgrade_0005_telegram_watchlists(connection: Connection) -> None:
    columns = {
        column["name"]
        for column in inspect(connection).get_columns("telegram_subscriptions")
    }
    if "watchlist_symbols" in columns:
        return
    connection.execute(
        text(
            """
            ALTER TABLE telegram_subscriptions
            ADD COLUMN watchlist_symbols JSON
            """
        )
    )


def _upgrade_0006_telegram_preferences(connection: Connection) -> None:
    columns = {
        column["name"]
        for column in inspect(connection).get_columns("telegram_subscriptions")
    }
    statements = [
        ("quiet_hours_start_minute", "INTEGER"),
        ("quiet_hours_end_minute", "INTEGER"),
        ("max_alerts_per_day", "INTEGER"),
        ("market_hours_only", "BOOLEAN NOT NULL DEFAULT 0"),
        ("daily_alert_count", "INTEGER NOT NULL DEFAULT 0"),
        ("daily_alert_date", "VARCHAR(10)"),
    ]
    for column_name, column_type in statements:
        if column_name in columns:
            continue
        connection.execute(
            text(
                f"""
                ALTER TABLE telegram_subscriptions
                ADD COLUMN {column_name} {column_type}
                """
            )
        )


def _upgrade_0007_runtime_budget_counters(connection: Connection) -> None:
    import app.models  # noqa: F401 - registers SQLAlchemy models before create_all

    Base.metadata.create_all(bind=connection, tables=[app.models.RuntimeBudgetCounter.__table__])


def _upgrade_0008_telegram_min_confidence(connection: Connection) -> None:
    columns = {
        column["name"]
        for column in inspect(connection).get_columns("telegram_subscriptions")
    }
    if "min_confidence" in columns:
        return
    connection.execute(
        text(
            """
            ALTER TABLE telegram_subscriptions
            ADD COLUMN min_confidence FLOAT
            """
        )
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        revision="0001_initial_schema",
        description="Create the baseline analysis and Telegram tables.",
        upgrade=_upgrade_0001_initial_schema,
    ),
    Migration(
        revision="0002_instrument_registry",
        description="Create the instrument registry table.",
        upgrade=_upgrade_0002_instrument_registry,
    ),
    Migration(
        revision="0003_provider_registry",
        description="Create the provider registry table.",
        upgrade=_upgrade_0003_provider_registry,
    ),
    Migration(
        revision="0004_source_snapshots",
        description="Create the raw source snapshots table.",
        upgrade=_upgrade_0004_source_snapshots,
    ),
    Migration(
        revision="0005_telegram_watchlists",
        description="Add per-chat Telegram watchlists.",
        upgrade=_upgrade_0005_telegram_watchlists,
    ),
    Migration(
        revision="0006_telegram_preferences",
        description="Add per-chat Telegram alert preferences.",
        upgrade=_upgrade_0006_telegram_preferences,
    ),
    Migration(
        revision="0007_runtime_budget_counters",
        description="Persist runtime budget counters in SQLite.",
        upgrade=_upgrade_0007_runtime_budget_counters,
    ),
    Migration(
        revision="0008_telegram_min_confidence",
        description="Add per-chat Telegram minimum confidence threshold.",
        upgrade=_upgrade_0008_telegram_min_confidence,
    ),
)


def _ensure_migration_table(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                revision VARCHAR(64) PRIMARY KEY,
                description VARCHAR(255) NOT NULL,
                applied_at DATETIME NOT NULL
            )
            """
        )
    )


def _applied_revisions(connection: Connection) -> set[str]:
    rows = connection.execute(select(SCHEMA_MIGRATIONS.c.revision)).all()
    return {row.revision for row in rows}


def apply_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        _ensure_migration_table(connection)
        applied = _applied_revisions(connection)
        pending = [migration for migration in MIGRATIONS if migration.revision not in applied]

        for migration in pending:
            migration.upgrade(connection)
            connection.execute(
                insert(SCHEMA_MIGRATIONS).values(
                    revision=migration.revision,
                    description=migration.description,
                    applied_at=datetime.now(timezone.utc),
                )
            )
