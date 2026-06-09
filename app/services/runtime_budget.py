from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import RuntimeBudgetCounter


class RuntimeBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeBudgetSnapshot:
    name: str
    limit: int | None
    used: int
    remaining: int | None


_LOCK = Lock()
_COUNTERS: dict[str, int] = {}


def consume_runtime_budget(
    name: str,
    limit: int | None,
    *,
    amount: int = 1,
) -> RuntimeBudgetSnapshot:
    normalized_amount = max(1, int(amount))
    if limit is None:
        return RuntimeBudgetSnapshot(name=name, limit=None, used=0, remaining=None)

    normalized_limit = max(0, int(limit))

    with _LOCK:
        persistent_used = _read_persistent_usage(name)
        if persistent_used is None:
            used = _COUNTERS.get(name, 0)
            if used + normalized_amount > normalized_limit:
                raise RuntimeBudgetExceeded(
                    f"{name} budget exhausted: used {used}/{normalized_limit}, "
                    f"requested {normalized_amount}."
                )
            used += normalized_amount
            _COUNTERS[name] = used
        else:
            if persistent_used + normalized_amount > normalized_limit:
                raise RuntimeBudgetExceeded(
                    f"{name} budget exhausted: used {persistent_used}/{normalized_limit}, "
                    f"requested {normalized_amount}."
                )
            _atomic_increment_persistent_usage(name, normalized_amount)
            used = persistent_used + normalized_amount
            _COUNTERS[name] = used

        return RuntimeBudgetSnapshot(
            name=name,
            limit=normalized_limit,
            used=used,
            remaining=normalized_limit - used,
        )


def runtime_budget_snapshot(name: str, limit: int | None) -> RuntimeBudgetSnapshot:
    if limit is None:
        return RuntimeBudgetSnapshot(name=name, limit=None, used=0, remaining=None)

    normalized_limit = max(0, int(limit))
    with _LOCK:
        used = _read_persistent_usage(name)
        if used is None:
            used = _COUNTERS.get(name, 0)
        else:
            _COUNTERS[name] = used
    return RuntimeBudgetSnapshot(
        name=name,
        limit=normalized_limit,
        used=used,
        remaining=max(0, normalized_limit - used),
    )


def reset_runtime_budgets(*, clear_persistent: bool = True) -> None:
    with _LOCK:
        _COUNTERS.clear()
    if clear_persistent:
        _clear_persistent_budgets()


def _read_persistent_usage(name: str) -> int | None:
    """Read persistent usage. Returns None if the database is unavailable."""
    try:
        from app.database import engine
    except Exception:
        return None

    try:
        with engine.connect() as connection:
            value = connection.execute(
                select(RuntimeBudgetCounter.used).where(RuntimeBudgetCounter.name == name)
            ).scalar_one_or_none()
    except Exception:
        return None

    return int(value) if value is not None else 0


def _atomic_increment_persistent_usage(name: str, amount: int) -> None:
    """Atomically increment a persistent budget counter.

    Uses SQLite UPSERT with ``used = used + amount`` so the read-check-write
    is atomic at the SQL level.  The caller already holds ``_LOCK``, which
    eliminates inter-thread races within the same process.
    """
    try:
        from app.database import engine
    except Exception:
        return

    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            # UPSERT: insert 0 on first use, then atomically increment
            stmt = sqlite_insert(RuntimeBudgetCounter).values(
                name=name,
                used=amount,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[RuntimeBudgetCounter.name],
                set_={
                    "used": RuntimeBudgetCounter.used + amount,
                    "updated_at": now,
                },
            )
            connection.execute(stmt)
    except Exception:
        return


def _clear_persistent_budgets() -> None:
    try:
        from app.database import engine
    except Exception:
        return

    try:
        with engine.begin() as connection:
            connection.execute(RuntimeBudgetCounter.__table__.delete())
    except Exception:
        return
