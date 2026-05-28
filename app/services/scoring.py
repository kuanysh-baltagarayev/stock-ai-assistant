from dataclasses import dataclass

from app.schemas import Fundamentals, Scores, TechnicalIndicators
from app.services.research_labels import (
    NEUTRAL_RESEARCH_LABELS,
    research_label_for_score,
    research_label_to_title,
)


RESEARCH_LABELS = set(NEUTRAL_RESEARCH_LABELS)


@dataclass(frozen=True)
class ScoringResult:
    scores: Scores
    recommendation: str
    short_reason: str
    reasons: list[str]


def score_stock(
    price: float,
    technicals: TechnicalIndicators,
    fundamentals: Fundamentals,
) -> ScoringResult:
    momentum_score, momentum_reasons = _momentum_score(price, technicals)
    valuation_score, valuation_reasons = _valuation_score(fundamentals)
    risk_score, risk_reasons = _risk_score(technicals)

    final_score = (
        momentum_score * 0.45
        + valuation_score * 0.35
        + (100 - risk_score) * 0.20
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


def _risk_score(technicals: TechnicalIndicators) -> tuple[float, list[str]]:
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

    return _clamp(score), reasons


def _recommendation(final_score: float, risk_score: float) -> str:
    return research_label_for_score(final_score, risk_score)


def _short_reason(recommendation: str, reasons: list[str]) -> str:
    base = research_label_to_title(recommendation)
    if not reasons:
        return f"{base}: not enough strong signals; review manually."
    return f"{base}: " + "; ".join(reasons[:3]) + "."


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))
