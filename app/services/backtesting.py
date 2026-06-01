"""Backtesting framework for analyzing score accuracy.

Compares historical scores (BUY, HOLD, SELL) against actual price movements
to measure model accuracy and identify systematic biases.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import AnalysisSnapshot


@dataclass(frozen=True)
class BacktestResult:
    """Result of analyzing one score's accuracy."""

    ticker: str
    score_date: datetime
    recommendation: str
    price_at_score: float
    price_check_date: datetime
    price_at_check: float
    price_change_pct: float
    correct: bool  # True if recommendation direction matches price change
    days_held: int


@dataclass(frozen=True)
class BacktestMetrics:
    """Metrics for backtesting results."""

    total_scores: int
    correct_predictions: int
    accuracy_pct: float  # correct_predictions / total_scores * 100
    buy_recommendations: int
    buy_correct: int
    buy_accuracy_pct: float
    hold_recommendations: int
    hold_correct: int
    hold_accuracy_pct: float
    sell_recommendations: int
    sell_correct: int
    sell_accuracy_pct: float
    avg_winning_trade_pct: float
    avg_losing_trade_pct: float
    avg_days_held: float


def assess_recommendation_accuracy(
    recommendation: str,
    price_at_score: float,
    price_at_check: float,
) -> bool:
    """Check if a recommendation was correct based on price movement.

    Args:
        recommendation: Score recommendation (BUY, HOLD, SELL, etc.)
        price_at_score: Price when score was generated
        price_at_check: Price at check date (e.g., 5 days later)

    Returns:
        True if recommendation matched price direction
    """
    if price_at_score == 0:
        return False

    price_change = price_at_check - price_at_score
    price_change_pct = (price_change / price_at_score) * 100

    # Map recommendations to expected directions
    if recommendation in {"BUY", "STRONG BUY"}:
        return price_change_pct > 0
    elif recommendation in {"SELL", "STRONG SELL"}:
        return price_change_pct < 0
    elif recommendation in {"HOLD", "WATCH", "NEUTRAL"}:
        # HOLD is correct if price doesn't move significantly (within ±2%)
        return -2 <= price_change_pct <= 2
    else:
        return False


def backtest_snapshot(
    snapshot: AnalysisSnapshot,
    price_at_check: float,
    check_date: datetime | None = None,
) -> BacktestResult:
    """Create backtest result by comparing score to actual price movement.

    Args:
        snapshot: Analysis snapshot with score and price
        price_at_check: Price at check date for comparison
        check_date: Date when price was checked. Defaults to today.

    Returns:
        BacktestResult with accuracy assessment
    """
    if check_date is None:
        check_date = datetime.now(timezone.utc)

    score_date = snapshot.created_at
    days_held = (check_date.date() - score_date.date()).days

    correct = assess_recommendation_accuracy(
        snapshot.recommendation,
        snapshot.price,
        price_at_check,
    )

    price_change_pct = ((price_at_check - snapshot.price) / snapshot.price * 100)

    return BacktestResult(
        ticker=snapshot.ticker,
        score_date=score_date,
        recommendation=snapshot.recommendation,
        price_at_score=snapshot.price,
        price_check_date=check_date,
        price_at_check=price_at_check,
        price_change_pct=round(price_change_pct, 2),
        correct=correct,
        days_held=days_held,
    )


def calculate_metrics(results: list[BacktestResult]) -> BacktestMetrics | None:
    """Calculate aggregate backtesting metrics.

    Args:
        results: List of BacktestResult objects

    Returns:
        BacktestMetrics with aggregate statistics, or None if no results
    """
    if not results:
        return None

    total = len(results)
    correct = sum(1 for r in results if r.correct)
    accuracy = (correct / total * 100) if total > 0 else 0

    # By recommendation type
    buys = [r for r in results if r.recommendation in {"BUY", "STRONG BUY"}]
    buy_correct = sum(1 for r in buys if r.correct)
    buy_accuracy = (buy_correct / len(buys) * 100) if buys else 0

    holds = [r for r in results if r.recommendation in {"HOLD", "WATCH", "NEUTRAL"}]
    hold_correct = sum(1 for r in holds if r.correct)
    hold_accuracy = (hold_correct / len(holds) * 100) if holds else 0

    sells = [r for r in results if r.recommendation in {"SELL", "STRONG SELL"}]
    sell_correct = sum(1 for r in sells if r.correct)
    sell_accuracy = (sell_correct / len(sells) * 100) if sells else 0

    # Win/loss analysis
    winning_trades = [r.price_change_pct for r in results if r.correct and r.price_change_pct > 0]
    losing_trades = [r.price_change_pct for r in results if r.correct and r.price_change_pct < 0]

    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = abs(sum(losing_trades) / len(losing_trades)) if losing_trades else 0

    # Average days held
    avg_days = sum(r.days_held for r in results) / total if total > 0 else 0

    return BacktestMetrics(
        total_scores=total,
        correct_predictions=correct,
        accuracy_pct=round(accuracy, 1),
        buy_recommendations=len(buys),
        buy_correct=buy_correct,
        buy_accuracy_pct=round(buy_accuracy, 1),
        hold_recommendations=len(holds),
        hold_correct=hold_correct,
        hold_accuracy_pct=round(hold_accuracy, 1),
        sell_recommendations=len(sells),
        sell_correct=sell_correct,
        sell_accuracy_pct=round(sell_accuracy, 1),
        avg_winning_trade_pct=round(avg_win, 2),
        avg_losing_trade_pct=round(avg_loss, 2),
        avg_days_held=round(avg_days, 1),
    )


def backtest_report(metrics: BacktestMetrics) -> list[str]:
    """Generate human-readable backtesting report.

    Args:
        metrics: BacktestMetrics with aggregate statistics

    Returns:
        List of report lines
    """
    report = [
        f"📊 Backtesting Report ({metrics.total_scores} scores analyzed)",
        "",
        f"Overall Accuracy: {metrics.accuracy_pct}% ({metrics.correct_predictions}/{metrics.total_scores})",
        f"Average hold period: {metrics.avg_days_held:.0f} days",
        "",
    ]

    if metrics.buy_recommendations > 0:
        report.append(
            f"💰 BUY recommendations: {metrics.buy_accuracy_pct}% accuracy "
            f"({metrics.buy_correct}/{metrics.buy_recommendations})"
        )

    if metrics.hold_recommendations > 0:
        report.append(
            f"⏸️ HOLD recommendations: {metrics.hold_accuracy_pct}% accuracy "
            f"({metrics.hold_correct}/{metrics.hold_recommendations})"
        )

    if metrics.sell_recommendations > 0:
        report.append(
            f"📉 SELL recommendations: {metrics.sell_accuracy_pct}% accuracy "
            f"({metrics.sell_correct}/{metrics.sell_recommendations})"
        )

    report.append("")

    if metrics.avg_winning_trade_pct > 0:
        report.append(
            f"📈 Average winning trade: +{metrics.avg_winning_trade_pct}%"
        )

    if metrics.avg_losing_trade_pct > 0:
        report.append(
            f"📉 Average losing trade: -{metrics.avg_losing_trade_pct}%"
        )

    # Interpretation
    report.append("")
    if metrics.accuracy_pct >= 60:
        report.append("✓ Model showing positive accuracy above 60%")
    elif metrics.accuracy_pct >= 55:
        report.append("⚠️ Model at baseline (55%). Room for improvement.")
    else:
        report.append("⚠️ Model accuracy below 55%. Consider review.")

    return report
