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
    political_risk_level: str | None = None  # None, "elevated", "high"
    yield_curve_spread: float | None = None  # 10Y-2Y spread (negative = inverted)
    payroll_growth: float | None = None  # Nonfarm payrolls month-over-month change


def build_macro_context(
    reference_date: datetime,
    fred_latest: dict[str, Any] | None = None,
    fred_history: dict[str, list[float]] | None = None,
    news_context: Any | None = None,
) -> MacroContext:
    """Build macroeconomic context from available data.

    Args:
        reference_date: Analysis timestamp
        fred_latest: Latest FRED macro data (dict with series -> value mapping)
        fred_history: Recent FRED value series (oldest-first) per series id,
            used to infer rate direction and year-over-year inflation trend.

    Returns:
        MacroContext with current economic conditions and alerts.
    """

    ref_date = reference_date.date()

    # Upcoming high-impact events in next 7 days
    upcoming = upcoming_events(reference_date=ref_date, days_ahead=7)
    high_impact = [e for e in upcoming if e.importance == "high"]
    event_names = [e.name for e in high_impact[:3]]

    # Infer macro conditions from available data
    fred_data = fred_latest or {}
    history = fred_history or {}
    fed_rate = fred_data.get("FEDFUNDS")
    unemployment = fred_data.get("UNRATE")
    inflation = fred_data.get("CPIAUCSL")

    # Volatility is high when:
    # - Fed meeting or major jobs/CPI report is imminent
    # - Inflation is elevated and rising
    # - Unemployment is at unusual levels
    volatility_level = _infer_volatility_level(fed_rate, unemployment, len(high_impact))

    # Rate direction from the FEDFUNDS trend window when available, else fall
    # back to a flat "stable" reading if we only have the latest point.
    rate_direction = _infer_rate_direction(history.get("FEDFUNDS"), fed_rate)

    # Inflation level from CPI year-over-year change when enough history is
    # present, else fall back to absolute CPI-index thresholds.
    inflation_level = _infer_inflation_level_from_history(history.get("CPIAUCSL"), inflation)

    political_risk_level: str | None = None
    if news_context is not None:
        from app.services.news_collector import political_risk_level_from_news
        political_risk_level = political_risk_level_from_news(news_context)

    # Yield curve spread (10Y-2Y). Negative values indicate inversion.
    yield_curve_spread: float | None = fred_data.get("T10Y2Y")
    try:
        yield_curve_spread = float(yield_curve_spread) if yield_curve_spread is not None else None
    except (TypeError, ValueError):
        yield_curve_spread = None

    # Payroll month-over-month change from history
    payroll_growth: float | None = None
    payrolls_history = history.get("PAYEMS")
    if payrolls_history and len(payrolls_history) >= 2:
        payroll_growth = payrolls_history[-1] - payrolls_history[-2]

    return MacroContext(
        reference_date=reference_date,
        upcoming_high_impact_events=event_names,
        recent_macro_data={
            "fed_rate": fed_rate,
            "unemployment": unemployment,
            "cpi": inflation,
            "t10y2y": yield_curve_spread,
            "payrolls": fred_data.get("PAYEMS"),
        },
        volatility_level=volatility_level,
        rate_direction=rate_direction,
        inflation_level=inflation_level,
        political_risk_level=political_risk_level,
        yield_curve_spread=yield_curve_spread,
        payroll_growth=payroll_growth,
    )


def macro_context_summary(macro: MacroContext) -> list[str]:
    """Return human-readable notes about macroeconomic context for alerts.

    These notes should be added to alert digests to give users context
    for interpreting stock movements.
    """
    notes: list[str] = []
    notes.extend(_fred_indicator_notes(macro))

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

    # Yield curve context
    yield_spread = macro.yield_curve_spread
    if yield_spread is not None and yield_spread < 0:
        notes.append(
            f"Кривая доходности инвертирована (10Y-2Y: {yield_spread:.2f}%) — "
            "исторический предиктор рецессии."
        )
    elif yield_spread is not None and yield_spread < 0.5:
        notes.append(
            f"Кривая доходности уплощается (10Y-2Y: {yield_spread:.2f}%)."
        )

    # Payroll growth context
    payroll = macro.payroll_growth
    if payroll is not None:
        if payroll < -200:
            notes.append(
                f"Nonfarm payrolls резко упали ({payroll:+.0f} тыс.) — "
                "возможен сигнал ослабления рынка труда."
            )
        elif payroll < 0:
            notes.append(
                f"Nonfarm payrolls сократились ({payroll:+.0f} тыс.)."
            )
        elif payroll > 300:
            notes.append(
                f"Nonfarm payrolls выросли ({payroll:+.0f} тыс.) — "
                "рынок труда остаётся сильным."
            )

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
    elif macro.rate_direction == "falling":
        notes.append(
            "Федеральная ставка снижается. Это поддерживает оценку высокорастущих компаний."
        )

    # Political/regulatory risk from breaking news
    if macro.political_risk_level == "high":
        notes.append(
            "Высокий политический/регуляторный риск: несколько острых новостей о тарифах, "
            "санкциях или регулировании. Возможна повышенная волатильность."
        )
    elif macro.political_risk_level == "elevated":
        notes.append(
            "Политический/регуляторный риск повышен: значимые новости о тарифах, "
            "санкциях или регулировании."
        )

    return notes


def _fred_indicator_notes(macro: MacroContext) -> list[str]:
    data = macro.recent_macro_data or {}
    fed_rate = _float_or_none(data.get("fed_rate"))
    unemployment = _float_or_none(data.get("unemployment"))
    cpi = _float_or_none(data.get("cpi"))
    notes: list[str] = []

    available_parts: list[str] = []
    if fed_rate is not None:
        available_parts.append(f"Fed funds {fed_rate:.2f}%")
    if unemployment is not None:
        available_parts.append(f"unemployment {unemployment:.2f}%")
    if cpi is not None:
        available_parts.append(f"CPI index {cpi:.2f}")

    if available_parts:
        notes.append(
            "FRED latest available macro snapshot: " + ", ".join(available_parts) + "."
        )

    missing = []
    if fed_rate is None:
        missing.append("Fed funds")
    if unemployment is None:
        missing.append("unemployment")
    if cpi is None:
        missing.append("CPI")
    if available_parts and missing:
        notes.append("FRED macro snapshot is incomplete: missing " + ", ".join(missing) + ".")

    if fed_rate is not None and fed_rate >= 5.0:
        notes.append(
            "Fed funds rate is elevated, so long-duration growth valuations may be more rate-sensitive."
        )
    elif fed_rate is not None and fed_rate <= 0.5:
        notes.append("Fed funds rate is very low, so liquidity conditions may be unusually loose.")

    if unemployment is not None and unemployment > 6.0:
        notes.append("Unemployment is high, which can point to weaker growth and defensive positioning.")
    elif unemployment is not None and unemployment < 3.5:
        notes.append("Unemployment is very low, which can keep wage and inflation pressure in focus.")

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


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _infer_rate_direction(
    history: list[float] | None,
    latest: float | None,
) -> str | None:
    """Infer Fed funds rate direction from a recent trend window.

    Compares the latest value against an earlier reference point. Small moves
    are treated as "stable" to avoid reacting to rounding noise. Falls back to
    "stable" when only a single point is available and ``None`` when there is no
    data at all.
    """
    series = [v for v in (history or []) if v is not None]
    if len(series) < 2:
        return "stable" if (series or latest is not None) else None

    recent = series[-1]
    earlier = series[0]
    delta = recent - earlier
    # FEDFUNDS is in percent; ~5bps is below meaningful policy-move resolution.
    if delta > 0.05:
        return "rising"
    if delta < -0.05:
        return "falling"
    return "stable"


def _infer_inflation_level_from_history(
    history: list[float] | None,
    latest: float | None,
) -> str | None:
    """Infer inflation level from CPI year-over-year change when possible.

    Needs ~13 monthly points to compare against a year ago. Falls back to the
    absolute CPI-index thresholds in :func:`_infer_inflation_level` when there
    is not enough history.

    YoY thresholds (Fed 2% target as the reference):
    - >= 3% = elevated
    - >= 2% = moderate
    - < 2%  = low
    """
    series = [v for v in (history or []) if v is not None]
    if len(series) < 13 or series[-13] == 0:
        return _infer_inflation_level(latest)

    year_ago = series[-13]
    current = series[-1]
    yoy_pct = (current - year_ago) / year_ago * 100.0
    if yoy_pct >= 3.0:
        return "elevated"
    if yoy_pct >= 2.0:
        return "moderate"
    return "low"
