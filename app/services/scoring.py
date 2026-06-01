from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.schemas import Fundamentals, Scores, TechnicalIndicators
from app.services.research_labels import (
    NEUTRAL_RESEARCH_LABELS,
    research_label_for_score,
    research_label_to_title,
)

if TYPE_CHECKING:
    from app.services.macro_context import MacroContext


RESEARCH_LABELS = set(NEUTRAL_RESEARCH_LABELS)


@dataclass(frozen=True)
class ScoringResult:
    scores: Scores
    recommendation: str
    short_reason: str
    reasons: list[str]


@dataclass(frozen=True)
class EventCatalyst:
    category: str
    severity: float
    reason: str


def score_stock(
    price: float,
    technicals: TechnicalIndicators,
    fundamentals: Fundamentals,
    macro_context: MacroContext | None = None,
    event_calendar: object | None = None,
    sec_filings: object | None = None,
    reference_time: datetime | None = None,
) -> ScoringResult:
    """Score a stock with optional macroeconomic context.

    Args:
        price: Current stock price
        technicals: Technical indicators (MA, RSI, etc.)
        fundamentals: Fundamental metrics (P/E, dividend, etc.)
        macro_context: Optional MacroContext for adaptive weighting

    Returns:
        ScoringResult with scores, recommendation, and reasons
    """
    momentum_score, momentum_reasons = _momentum_score(price, technicals)
    valuation_score, valuation_reasons = _valuation_score(fundamentals)
    risk_score, risk_reasons = _risk_score(
        technicals,
        macro_context=macro_context,
        event_calendar=event_calendar,
        sec_filings=sec_filings,
        reference_time=reference_time,
    )

    # Determine weights based on macro context
    if macro_context:
        momentum_w, valuation_w, risk_w = _adaptive_weights(macro_context)
    else:
        momentum_w, valuation_w, risk_w = 0.45, 0.35, 0.20

    final_score = (
        momentum_score * momentum_w
        + valuation_score * valuation_w
        + (100 - risk_score) * risk_w
    )
    final_score = round(_clamp(final_score), 2)
    recommendation = research_label_for_score(final_score, risk_score)
    reasons = momentum_reasons + valuation_reasons + risk_reasons

    scores = Scores(
        momentum_score=round(momentum_score, 2),
        valuation_score=round(valuation_score, 2),
        risk_score=round(risk_score, 2),
        final_score=final_score,
    )

    return ScoringResult(
        scores=scores,
        recommendation=recommendation,
        short_reason=_short_reason(recommendation, reasons),
        reasons=reasons,
    )


def _momentum_score(price: float, technicals: TechnicalIndicators) -> tuple[float, list[str]]:
    score = 50.0
    reasons: list[str] = []

    if technicals.moving_average_50 is not None:
        if price > technicals.moving_average_50:
            score += 15
            reasons.append("price is above MA50")
        else:
            score -= 15
            reasons.append("price is below MA50")

    if technicals.moving_average_200 is not None:
        if price > technicals.moving_average_200:
            score += 20
            reasons.append("price is above MA200")
        else:
            score -= 20
            reasons.append("price is below MA200")

    if technicals.change_1m_pct is not None:
        if technicals.change_1m_pct > 5:
            score += 10
            reasons.append("1-month momentum is positive")
        elif technicals.change_1m_pct < -5:
            score -= 10
            reasons.append("1-month momentum is weak")

    if technicals.change_6m_pct is not None:
        if technicals.change_6m_pct > 15:
            score += 10
            reasons.append("6-month trend is strong")
        elif technicals.change_6m_pct < -15:
            score -= 10
            reasons.append("6-month trend is weak")

    if technicals.rsi is not None:
        if technicals.rsi > 80:
            score -= 25
            reasons.append("RSI shows strong overheating")
        elif technicals.rsi > 70:
            score -= 15
            reasons.append("RSI is overbought")
        elif technicals.rsi < 25:
            score -= 5
            reasons.append("RSI is deeply oversold")
        elif technicals.rsi < 30:
            score += 5
            reasons.append("RSI may indicate oversold conditions")

    return _clamp(score), reasons


def _valuation_score(fundamentals: Fundamentals) -> tuple[float, list[str]]:
    score = 55.0
    reasons: list[str] = []

    trailing_pe = fundamentals.trailing_pe
    if trailing_pe is not None:
        if trailing_pe <= 0:
            score -= 10
            reasons.append("trailing P/E is not meaningful")
        elif trailing_pe < 15:
            score += 20
            reasons.append("valuation looks inexpensive by trailing P/E")
        elif trailing_pe < 25:
            score += 10
            reasons.append("valuation looks reasonable by trailing P/E")
        elif trailing_pe > 60:
            score -= 30
            reasons.append("trailing P/E is very high")
        elif trailing_pe > 40:
            score -= 15
            reasons.append("trailing P/E is elevated")

    forward_pe = fundamentals.forward_pe
    if forward_pe is not None:
        if forward_pe > 50:
            score -= 10
            reasons.append("forward P/E is high")
        elif trailing_pe and forward_pe < trailing_pe * 0.8:
            score += 8
            reasons.append("forward P/E is lower than trailing P/E")

    if fundamentals.revenue_growth is not None:
        if fundamentals.revenue_growth > 0.15:
            score += 15
            reasons.append("revenue growth is strong")
        elif fundamentals.revenue_growth > 0.05:
            score += 8
            reasons.append("revenue growth is positive")
        elif fundamentals.revenue_growth < 0:
            score -= 15
            reasons.append("revenue growth is negative")

    if fundamentals.profit_margins is not None:
        if fundamentals.profit_margins > 0.20:
            score += 12
            reasons.append("profit margins are strong")
        elif fundamentals.profit_margins > 0.10:
            score += 6
            reasons.append("profit margins are healthy")
        elif fundamentals.profit_margins < 0:
            score -= 20
            reasons.append("profit margins are negative")

    if fundamentals.debt_to_equity is not None:
        if fundamentals.debt_to_equity > 200:
            score -= 15
            reasons.append("debt/equity is high")
        elif fundamentals.debt_to_equity > 100:
            score -= 8
            reasons.append("debt/equity is elevated")
        elif fundamentals.debt_to_equity < 50:
            score += 6
            reasons.append("debt/equity is conservative")

    return _clamp(score), reasons


def _risk_score(
    technicals: TechnicalIndicators,
    *,
    macro_context: MacroContext | None = None,
    event_calendar: object | None = None,
    sec_filings: object | None = None,
    reference_time: datetime | None = None,
) -> tuple[float, list[str]]:
    score = 35.0
    reasons: list[str] = []

    if technicals.volatility_pct is not None:
        if technicals.volatility_pct < 20:
            score -= 15
            reasons.append("volatility is low")
        elif technicals.volatility_pct > 60:
            score += 30
            reasons.append("volatility is very high")
        elif technicals.volatility_pct > 35:
            score += 15
            reasons.append("volatility is elevated")

    if technicals.max_drawdown_pct is not None:
        drawdown_abs = abs(technicals.max_drawdown_pct)
        if drawdown_abs < 15:
            score -= 10
            reasons.append("max drawdown is limited")
        elif drawdown_abs > 50:
            score += 25
            reasons.append("max drawdown is severe")
        elif drawdown_abs > 30:
            score += 15
            reasons.append("max drawdown is large")

    if technicals.rsi is not None and technicals.rsi > 75:
        score += 10
        reasons.append("overbought RSI adds short-term risk")

    if technicals.change_1d_pct is not None and abs(technicals.change_1d_pct) > 5:
        score += 5
        reasons.append("daily move is unusually large")

    catalyst_adjustment, catalyst_reasons = _event_catalyst_risk_adjustment(
        macro_context=macro_context,
        event_calendar=event_calendar,
        sec_filings=sec_filings,
        reference_time=reference_time,
    )
    score += catalyst_adjustment
    reasons.extend(catalyst_reasons)

    return _clamp(score), reasons


def _event_catalyst_risk_adjustment(
    *,
    macro_context: MacroContext | None = None,
    event_calendar: object | None = None,
    sec_filings: object | None = None,
    reference_time: datetime | None = None,
) -> tuple[float, list[str]]:
    now = reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    catalysts = (
        _macro_event_catalyst(macro_context)
        + _company_event_catalyst(event_calendar, now=now)
        + _sec_filing_catalyst(sec_filings, now=now)
    )
    if not catalysts:
        return 0.0, []

    catalysts.sort(key=lambda catalyst: catalyst.severity, reverse=True)
    weights = (1.0, 0.6, 0.35)
    adjustment = 0.0
    for index, catalyst in enumerate(catalysts[:3]):
        adjustment += catalyst.severity * weights[index]

    category_count = len({catalyst.category for catalyst in catalysts})
    if category_count >= 3:
        adjustment += 4.0
    elif category_count == 2:
        adjustment += 2.0

    reasons: list[str] = []
    for catalyst in catalysts[:2]:
        if catalyst.reason not in reasons:
            reasons.append(catalyst.reason)
    if category_count >= 2:
        reasons.append("multiple near-term catalysts can amplify event risk")

    return min(round(adjustment, 2), 20.0), reasons


def _macro_event_catalyst(macro_context: MacroContext | None) -> list[EventCatalyst]:
    if macro_context is None or not macro_context.upcoming_high_impact_events:
        return []

    event_count = len(macro_context.upcoming_high_impact_events)
    if event_count >= 3:
        return [
            EventCatalyst(
                category="macro",
                severity=9.0,
                reason="multiple high-impact macro events are imminent",
            )
        ]
    if event_count == 2:
        return [
            EventCatalyst(
                category="macro",
                severity=7.0,
                reason="two high-impact macro events are imminent",
            )
        ]
    return [
        EventCatalyst(
            category="macro",
            severity=4.0,
            reason="a high-impact macro event is imminent",
        )
    ]


def _company_event_catalyst(
    event_calendar: object | None,
    *,
    now: datetime,
) -> list[EventCatalyst]:
    if not event_calendar:
        return []

    events = getattr(event_calendar, "upcoming_events", None)
    if events is None and isinstance(event_calendar, dict):
        events = event_calendar.get("upcoming_events")
    if not events:
        return []

    nearest_earnings_days: int | None = None
    for event in events:
        if isinstance(event, dict):
            name = str(event.get("name") or "").lower()
            scheduled_at = event.get("scheduled_at") or event.get("window_start_at")
        else:
            name = str(getattr(event, "name", "")).lower()
            scheduled_at = getattr(event, "scheduled_at", None) or getattr(
                event,
                "window_start_at",
                None,
            )
        if name != "earnings":
            continue
        scheduled_dt = _parse_datetime_like(scheduled_at)
        if scheduled_dt is None:
            continue
        days_until = (scheduled_dt.date() - now.date()).days
        if days_until < 0:
            continue
        if nearest_earnings_days is None or days_until < nearest_earnings_days:
            nearest_earnings_days = days_until

    if nearest_earnings_days is None:
        return []
    if nearest_earnings_days <= 3:
        return [
            EventCatalyst(
                category="company_event",
                severity=9.0,
                reason="earnings are imminent and can sharply raise event risk",
            )
        ]
    if nearest_earnings_days <= 7:
        return [
            EventCatalyst(
                category="company_event",
                severity=6.0,
                reason="upcoming earnings keep event risk elevated",
            )
        ]
    if nearest_earnings_days <= 14:
        return [
            EventCatalyst(
                category="company_event",
                severity=3.0,
                reason="earnings are approaching",
            )
        ]
    return []


def _sec_filing_catalyst(
    sec_filings: object | None,
    *,
    now: datetime,
) -> list[EventCatalyst]:
    if not sec_filings:
        return []

    filings = getattr(sec_filings, "recent_filings", None)
    if filings is None and isinstance(sec_filings, dict):
        filings = sec_filings.get("recent_filings")
    if not filings:
        return []

    strongest: EventCatalyst | None = None
    for filing in filings[:3]:
        if isinstance(filing, dict):
            form_type = str(filing.get("form_type") or "").upper()
            filing_date = filing.get("filing_date")
        else:
            form_type = str(getattr(filing, "form_type", "")).upper()
            filing_date = getattr(filing, "filing_date", None)

        filing_dt = _parse_filing_date(filing_date)
        if not form_type or filing_dt is None:
            continue

        age_days = max(0, (now.date() - filing_dt.date()).days)
        severity = 0.0
        reason: str | None = None

        if form_type == "8-K":
            if age_days <= 7:
                severity = 8.0
                reason = "recent 8-K adds event risk"
            elif age_days <= 30:
                severity = 4.0
                reason = "recent 8-K still adds event risk"
        elif form_type in {"10-Q", "10-Q/A"}:
            if age_days <= 14:
                severity = 6.0
                reason = "fresh 10-Q adds reporting-event risk"
            elif age_days <= 45:
                severity = 3.0
                reason = "recent 10-Q keeps reporting risk elevated"
        elif form_type in {"10-K", "10-K/A"}:
            if age_days <= 21:
                severity = 5.0
                reason = "fresh 10-K adds annual-report event risk"
            elif age_days <= 60:
                severity = 2.0
                reason = "recent 10-K keeps event risk elevated"
        elif form_type in {"S-1", "DEF 14A"} and age_days <= 30:
            severity = 4.0
            reason = f"recent {form_type} adds event risk"

        if severity <= 0 or reason is None:
            continue

        catalyst = EventCatalyst(category="sec_filing", severity=severity, reason=reason)
        if strongest is None or catalyst.severity > strongest.severity:
            strongest = catalyst

    return [strongest] if strongest is not None else []


def _parse_filing_date(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_datetime_like(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _recommendation(final_score: float, risk_score: float) -> str:
    return research_label_for_score(final_score, risk_score)


def _short_reason(recommendation: str, reasons: list[str]) -> str:
    base = research_label_to_title(recommendation)
    if not reasons:
        return f"{base}: not enough strong signals; review manually."
    return f"{base}: " + "; ".join(reasons[:3]) + "."


def _adaptive_weights(macro_context: MacroContext) -> tuple[float, float, float]:
    """Determine score weights based on macroeconomic context.

    Standard weights: momentum=0.45, valuation=0.35, risk=0.20

    Adaptive adjustments:
    - HIGH volatility: boost momentum (techicals matter more in fast markets),
      reduce valuation (long-term fundamentals less relevant)
    - RISING Fed rates: boost risk assessment, reduce valuation
    - ELEVATED inflation: boost risk (duration risk), reduce valuation

    Returns:
        Tuple of (momentum_weight, valuation_weight, risk_weight)
    """
    momentum_w = 0.45
    valuation_w = 0.35
    risk_w = 0.20

    # High volatility: short-term technicals matter more
    if macro_context.volatility_level == "high":
        momentum_w += 0.05
        valuation_w -= 0.05

    # Fed rate rising: risk increases (duration risk, refinancing stress)
    if macro_context.rate_direction == "rising":
        risk_w += 0.03
        valuation_w -= 0.03

    # Elevated inflation: real returns under pressure, duration risk
    if macro_context.inflation_level == "elevated":
        risk_w += 0.02
        valuation_w -= 0.02
        momentum_w += 0.01

    # Normalize weights to sum to 1.0
    total = momentum_w + valuation_w + risk_w
    return (
        round(momentum_w / total, 3),
        round(valuation_w / total, 3),
        round(risk_w / total, 3),
    )


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))
