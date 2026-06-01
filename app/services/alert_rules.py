"""Threshold-based alert rules for per-ticker price and signal events.

Rules are stored as JSON in TelegramSubscription.alert_rules:
  [{"ticker": "AAPL", "kind": "price_below", "value": 300.0, "last_fired_at": None}, ...]

Supported kinds:
  price_below   — fires when price < value
  price_above   — fires when price > value
  pct_move      — fires when abs(daily pct change) >= value (e.g. 5 means ±5%)
  recommendation — fires when recommendation matches value (e.g. "SELL", "BUY")
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


_RECOMMENDATION_ALIASES: dict[str, str] = {
    "buy": "BUY",
    "sell": "SELL",
    "hold": "HOLD",
    "watch": "WATCH",
    "neutral": "NEUTRAL",
    "high_interest": "HIGH_INTEREST",
}


def parse_rule(text: str) -> dict[str, Any] | None:
    """Parse a user-typed alert rule string into a rule dict.

    Accepted formats (case-insensitive):
      "AAPL < 300"      -> price_below 300
      "AAPL > 350"      -> price_above 350
      "AAPL move 5"     -> pct_move 5  (fires on ±5% daily move)
      "AAPL sell"       -> recommendation SELL
      "AAPL buy"        -> recommendation BUY
    Returns None if the format is not recognised.
    """
    text = text.strip()
    # price comparison: AAPL < 300 / AAPL > 350.5
    m = re.fullmatch(
        r"([A-Za-z0-9.\-]{1,12})\s*([<>])\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )
    if m:
        ticker, op, val = m.group(1).upper(), m.group(2), float(m.group(3))
        return {
            "ticker": ticker,
            "kind": "price_below" if op == "<" else "price_above",
            "value": val,
            "last_fired_at": None,
        }

    # pct move: AAPL move 5
    m = re.fullmatch(
        r"([A-Za-z0-9.\-]{1,12})\s+(?:move|±|pm)\s+([0-9]+(?:\.[0-9]+)?)",
        text,
        re.IGNORECASE,
    )
    if m:
        return {
            "ticker": m.group(1).upper(),
            "kind": "pct_move",
            "value": float(m.group(2)),
            "last_fired_at": None,
        }

    # recommendation: AAPL sell / AAPL buy
    m = re.fullmatch(
        r"([A-Za-z0-9.\-]{1,12})\s+("
        + "|".join(_RECOMMENDATION_ALIASES.keys())
        + r")",
        text,
        re.IGNORECASE,
    )
    if m:
        return {
            "ticker": m.group(1).upper(),
            "kind": "recommendation",
            "value": _RECOMMENDATION_ALIASES[m.group(2).lower()],
            "last_fired_at": None,
        }

    return None


def evaluate_rules(
    rules: list[dict[str, Any]],
    *,
    ticker: str,
    price: float,
    prev_close: float | None,
    recommendation: str | None,
) -> list[dict[str, Any]]:
    """Return the subset of rules that are currently firing for a ticker.

    Only evaluates rules matching the given ticker. Does not mutate rules;
    caller is responsible for updating last_fired_at after acting on results.
    """
    fired: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("ticker", "").upper() != ticker.upper():
            continue
        kind = rule.get("kind")
        value = rule.get("value")
        if kind == "price_below" and isinstance(value, (int, float)):
            if price < value:
                fired.append({**rule, "reason": f"{ticker} цена {price:.2f} ниже {value:.2f}"})
        elif kind == "price_above" and isinstance(value, (int, float)):
            if price > value:
                fired.append({**rule, "reason": f"{ticker} цена {price:.2f} выше {value:.2f}"})
        elif kind == "pct_move" and isinstance(value, (int, float)) and prev_close:
            pct = (price - prev_close) / prev_close * 100
            if abs(pct) >= value:
                direction = "вырос" if pct > 0 else "упал"
                fired.append({**rule, "reason": f"{ticker} {direction} на {abs(pct):.1f}% за день"})
        elif kind == "recommendation" and isinstance(value, str):
            if (recommendation or "").upper() == value.upper():
                fired.append({**rule, "reason": f"{ticker} рекомендация изменилась на {value}"})
    return fired


def format_rule(rule: dict[str, Any]) -> str:
    """Human-readable one-liner for a rule."""
    kind = rule.get("kind", "")
    ticker = rule.get("ticker", "")
    value = rule.get("value")
    if kind == "price_below":
        return f"{ticker} < {value}"
    if kind == "price_above":
        return f"{ticker} > {value}"
    if kind == "pct_move":
        return f"{ticker} движение ±{value}%"
    if kind == "recommendation":
        return f"{ticker} → {value}"
    return str(rule)


def mark_fired(rule: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the rule with last_fired_at set to now."""
    return {**rule, "last_fired_at": datetime.now(timezone.utc).isoformat()}


def is_recently_fired(rule: dict[str, Any], *, cooldown_hours: float = 4.0) -> bool:
    """True if the rule fired within cooldown_hours (prevents spam re-fires)."""
    last = rule.get("last_fired_at")
    if not last:
        return False
    try:
        fired_at = datetime.fromisoformat(str(last))
        if fired_at.tzinfo is None:
            fired_at = fired_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - fired_at).total_seconds() / 3600
        return elapsed < cooldown_hours
    except (ValueError, TypeError):
        return False
