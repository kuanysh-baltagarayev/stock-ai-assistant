from __future__ import annotations

from collections import Counter
from typing import Any


def format_operation_summary(
    issues: list[Any] | None = None,
    notes: list[str] | None = None,
) -> list[str]:
    counts: Counter[str] = Counter()

    for issue in issues or []:
        message = _issue_text(issue)
        category = _issue_category(message)
        counts[category] += 1

    for note in notes or []:
        category = _issue_category(note)
        if category in {"openai", "telegram"}:
            counts[category] += 1

    parts: list[str] = []
    market_data_count = counts.get("market_data", 0)
    openai_count = counts.get("openai", 0)
    telegram_count = counts.get("telegram", 0)

    if market_data_count:
        parts.append(f"market-data: {market_data_count}")
    if openai_count:
        parts.append(f"OpenAI: {openai_count}")
    if telegram_count:
        parts.append(f"Telegram: {telegram_count}")

    if not parts:
        return []
    return [f"Сводка операций: {', '.join(parts)}"]


def _issue_text(issue: Any) -> str:
    if isinstance(issue, str):
        return issue
    message = getattr(issue, "error", None)
    if isinstance(message, str) and message:
        return message
    return str(issue)


def _issue_category(message: str) -> str:
    lowered = message.lower()
    if "openai" in lowered:
        return "openai"
    if "telegram" in lowered or "sendMessage" in message or "getme" in lowered:
        return "telegram"
    return "market_data"
