from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


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
        used = _COUNTERS.get(name, 0)
        if used + normalized_amount > normalized_limit:
            raise RuntimeBudgetExceeded(
                f"{name} budget exhausted: used {used}/{normalized_limit}, "
                f"requested {normalized_amount}."
            )
        used += normalized_amount
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
        used = _COUNTERS.get(name, 0)
    return RuntimeBudgetSnapshot(
        name=name,
        limit=normalized_limit,
        used=used,
        remaining=max(0, normalized_limit - used),
    )


def reset_runtime_budgets() -> None:
    with _LOCK:
        _COUNTERS.clear()
