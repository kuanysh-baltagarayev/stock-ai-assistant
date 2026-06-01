"""Macroeconomic context for alert enrichment.

Provides macroeconomic conditions that should influence alert interpretation.
High inflation + Fed rate hikes = tech stocks under pressure.
Jobs reports miss expectations = market volatility spike likely.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.economic_calendar import upcoming_events


@dataclass(frozen=True)
class MacroContext:
    """Macroeconomic context snapshot."""

    reference_date: datetime
    upcoming_high_impact_events: list[str]
    recent_macro_data: dict[str, float | None]
    volatility_level: str  # "low", "medium", "high"
    rate_direction: str | None  # "rising", "falling", "stable", None
    inflation_level: str | None  # "low", "moderate", "elevated", None


def build_macro_context(
    reference_date: datetime,
    fred_latest: dict[str, Any] | None = None,
) -> MacroContext:
    """Build macroeconomic context from available data.

    Args:
        reference_date: Analysis timestamp
        fred_latest: Latest FRED macro data (dict with series -> value mapping)

    Returns:
        MacroContext with current economic conditions and alerts.
    """
    from datetime import timedelta

    ref_date = reference_date.date()

    # Upcoming high-impact events in next 7 days
    upcoming = upcoming_events(reference_date=ref_date, days_ahead=7)
    high_impact = [e for e in upcoming if e.importance == "high"]
    event_names = [e.name for e in high_impact[:3]]

    # Infer macro conditions from available data
    fred_data = fred_latest or {}
    fed_rate = fred_data.get("FEDFUNDS")
    unemployment = fred_data.get("UNRATE")
    inflation = fred_data.get("CPIAUCSL")

    # Volatility is high when:
    # - Fed meeting or major jobs/CPI report is imminent
    # - Inflation is elevated and rising
    # - Unemployment is at unusual levels
    volatility_level = _infer_volatility_level(fed_rate, unemployment, len(high_impact))

    # Rate direction from FEDFUNDS trend (simplified: any data = stable)
    rate_direction = "stable" if fed_rate is not None else None

    # Inflation level from CPI (simplified)
    inflation_level = _infer_inflation_level(inflation)

    return MacroContext(
        reference_date=reference_date,
        upcoming_high_impact_events=event_names,
        recent_macro_data={
            "fed_rate": fed_rate,
            "unemployment": unemployment,
            "cpi": inflation,
        },
        volatility_level=volatility_level,
        rate_direction=rate_direction,
        inflation_level=inflation_level,
    )


def macro_context_summary(macro: MacroContext) -> list[str]:
    """Return human-readable notes about macroeconomic context for alerts.

    These notes should be added to alert digests to give users context
    for interpreting stock movements.
    """
    notes: list[str] = []

    # Upcoming events warning
    if macro.upcoming_high_impact_events:
        event_list = ", ".join(macro.upcoming_high_impact_events)
        notes.append(f"Внимание: в ближайшие дни важные события: {event_list}.")

    # Volatility context
    if macro.volatility_level == "high":
        notes.append(
            "Макро-волатильность повышена (Fed решения, экономические отчёты). "
            "Движения акций могут быть острыми."
        )
    elif macro.volatility_level == "medium":
        notes.append("Ожидается умеренная волатильность из макро-факторов.")

    # Inflation context
    if macro.inflation_level == "elevated":
        notes.append(
            "Инфляция повышена. Технологичные акции и растущие компании "
            "могут быть под давлением."
        )

    # Fed rate context
    if macro.rate_direction == "rising":
        notes.append(
            "Федеральная ставка растёт. Это давит на оценку высокорастущих компаний."
        )

    return notes


def alert_weight_adjustment(macro: MacroContext) -> float:
    """Return a multiplier for alert weight based on macro conditions.

    - 1.0 = normal alert weight
    - 1.5 = amplified alert (high volatility or major event)
    - 0.7 = dampened alert (stable macro conditions)
    """
    weight = 1.0

    # Amplify when high-impact events are imminent
    if macro.upcoming_high_impact_events:
        weight += 0.3

    # Amplify during high volatility
    if macro.volatility_level == "high":
        weight += 0.2

    # Dampen when macro is stable and inflation moderate
    if macro.volatility_level == "low" and macro.inflation_level != "elevated":
        weight -= 0.2
        weight = max(0.7, weight)

    return round(weight, 2)


def _infer_volatility_level(
    fed_rate: float | None,
    unemployment: float | None,
    upcoming_event_count: int,
) -> str:
    """Infer volatility level from macro indicators."""
    if upcoming_event_count >= 2:
        return "high"

    # Unemployment extremes = volatility
    if unemployment is not None and (unemployment < 3.5 or unemployment > 6.0):
        return "medium"

    # Fed at extremes (very low or very high) = volatility
    if fed_rate is not None and (fed_rate < 0.5 or fed_rate > 5.0):
        return "medium"

    return "low"


def _infer_inflation_level(cpi: float | None) -> str | None:
    """Infer inflation level from CPI index.

    CPI base = 100 in 2015-2016. Levels:
    - 320+ = high inflation (> 3%)
    - 310-320 = moderate inflation (2-3%)
    - < 310 = low inflation (< 2%)
    """
    if cpi is None:
        return None

    if cpi >= 320:
        return "elevated"
    elif cpi >= 310:
        return "moderate"
    return "low"
