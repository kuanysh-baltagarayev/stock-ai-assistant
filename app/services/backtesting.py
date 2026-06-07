"""Backtesting framework for analyzing score accuracy.

Compares historical scores (HIGH_INTEREST, WATCH, NEUTRAL, CAUTION, HIGH_RISK)
against actual price movements over fixed horizons to measure accuracy and
identify systematic biases.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from app.models import AnalysisSnapshot

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Standard horizons in trading days.
DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 20)

# Labels that predict upward price movement.
_BULLISH_LABELS: frozenset[str] = frozenset({"HIGH_INTEREST", "WATCH"})

# Labels that predict downward price movement.
_BEARISH_LABELS: frozenset[str] = frozenset({"CAUTION", "HIGH_RISK"})

# Labels that expect no significant movement.
_NEUTRAL_LABELS: frozenset[str] = frozenset({"NEUTRAL"})

# Neutral band (±%) — a prediction is "correct" for neutral labels when the
# actual price change stays within this band.
_NEUTRAL_BAND_PCT = 2.0

# Significant-move threshold (±%) — used for false-positive/negative counts.
# A move beyond this band is "significant".
_SIGNIFICANT_MOVE_PCT = 2.0

# Minimum number of snapshots needed for a meaningful report.
_MIN_SNAPSHOTS_FOR_REPORT = 3

# How many calendar days to fetch before the earliest snapshot so the price-on
# or-after logic has a warm-up buffer.
_HISTORY_BUFFER_DAYS = 10


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestResult:
    """Result of checking one snapshot's accuracy over one horizon."""

    ticker: str
    score_date: datetime
    recommendation: str
    price_at_score: float
    horizon: int  # trading days
    price_check_date: datetime
    price_at_check: float
    price_change_pct: float
    correct: bool


@dataclass(frozen=True)
class LabelHorizonMetrics:
    """Accuracy for a (label × horizon) bucket."""

    label: str
    horizon: int
    total: int
    correct: int
    accuracy_pct: float
    avg_return_pct: float | None = None


@dataclass(frozen=True)
class BacktestMetrics:
    """Aggregate backtesting statistics."""

    total_scores: int
    correct_predictions: int
    accuracy_pct: float
    false_positives: int
    false_negatives: int
    avg_return_pct: float | None
    by_label_horizon: tuple[LabelHorizonMetrics, ...]
    insufficient_data: bool = False


# ---------------------------------------------------------------------------
# Price lookup helpers
# ---------------------------------------------------------------------------


def _lookup_close_price(
    history: pd.DataFrame,
    target_date: datetime,
) -> float | None:
    """Return the adjusted close price on or after *target_date*.

    Searches forward up to 10 trading days so that a snapshot created on a
    Friday evening still finds Monday's close.  Returns ``None`` when the
    history does not cover the target date.
    """
    if history is None or history.empty:
        return None

    close_col: str | None = None
    for candidate in ("Adj Close", "Close", "close", "adj close"):
        if candidate in history.columns:
            close_col = candidate
            break
    if close_col is None:
        # MultiIndex columns from yfinance
        try:
            if isinstance(history.columns, pd.MultiIndex):
                for first in ("Adj Close", "Close", "close", "adj close"):
                    for second in (target_date.strftime("%Y-%m-%d"),):
                        if (first, second) in history.columns:
                            close_col = (first, second)
                            break
                    if close_col:
                        break
        except Exception:
            pass
    if close_col is None:
        return None

    target_naive = target_date.replace(tzinfo=None)
    # Normalize the index to naive datetime for comparison
    history_idx = history.index
    if hasattr(history_idx, "tz") and history_idx.tz is not None:
        history_idx = history_idx.tz_localize(None)

    for offset in range(11):  # 0..10 trading days forward
        check_date = target_naive + timedelta(days=offset)
        try:
            row = history.loc[check_date.strftime("%Y-%m-%d")]
        except KeyError:
            continue
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        try:
            price = float(row[close_col])
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


# ---------------------------------------------------------------------------
# Accuracy assessment
# ---------------------------------------------------------------------------


def assess_recommendation_accuracy(
    recommendation: str,
    price_at_score: float,
    price_at_check: float,
) -> bool:
    """Check if a research-label recommendation was correct.

    Label semantics:
        HIGH_INTEREST / WATCH   → price ↑ is correct
        NEUTRAL                → |change| ≤ 2 %  is correct
        CAUTION / HIGH_RISK    → price ↓ is correct

    Args:
        recommendation: One of ``HIGH_INTEREST``, ``WATCH``, ``NEUTRAL``,
            ``CAUTION``, ``HIGH_RISK``.
        price_at_score: Price when the score was generated.
        price_at_check: Price at the check date.

    Returns:
        ``True`` if the recommendation matched the price direction.
    """
    if price_at_score <= 0:
        return False

    change_pct = (price_at_check - price_at_score) / price_at_score * 100

    if recommendation in _BULLISH_LABELS:
        return change_pct > 0
    if recommendation in _BEARISH_LABELS:
        return change_pct < 0
    if recommendation in _NEUTRAL_LABELS:
        return abs(change_pct) <= _NEUTRAL_BAND_PCT
    # Unknown label — cannot assess
    return False


def _is_false_positive(recommendation: str, change_pct: float) -> bool:
    """A prediction was a false positive when the market moved the *opposite*
    way by a significant margin."""
    if recommendation in _BULLISH_LABELS:
        return change_pct <= -_SIGNIFICANT_MOVE_PCT
    if recommendation in _BEARISH_LABELS:
        return change_pct >= _SIGNIFICANT_MOVE_PCT
    return False


def _is_false_negative(recommendation: str, change_pct: float) -> bool:
    """A neutral prediction is a false negative when the market *did* move
    significantly (the model failed to flag it)."""
    if recommendation in _NEUTRAL_LABELS:
        return abs(change_pct) > _SIGNIFICANT_MOVE_PCT
    return False


# ---------------------------------------------------------------------------
# Multi-snapshot backtesting
# ---------------------------------------------------------------------------


def backtest_snapshots(
    snapshots: list[AnalysisSnapshot],
    history: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> list[BacktestResult]:
    """Backtest a list of snapshots against historical price data.

    For each snapshot and each horizon, looks up the close price at
    ``snapshot.created_at + horizon`` trading days and records whether the
    recommendation was correct.

    Args:
        snapshots: Analysis snapshots ordered by ``created_at`` (any order).
        history: Price DataFrame from yfinance with a DatetimeIndex and an
            ``Adj Close`` or ``Close`` column.
        horizons: One or more look-ahead horizons in trading days.

    Returns:
        List of ``BacktestResult`` objects (one per snapshot × horizon).
    """
    results: list[BacktestResult] = []
    for snapshot in snapshots:
        if snapshot.price is None or snapshot.price <= 0:
            continue
        for horizon in horizons:
            # Look up price ~horizon trading days forward from the score date.
            target_date = snapshot.created_at + timedelta(days=horizon * 1.4)
            check_price = _lookup_close_price(history, target_date)
            if check_price is None or check_price <= 0:
                continue
            change_pct = (check_price - snapshot.price) / snapshot.price * 100
            correct = assess_recommendation_accuracy(
                snapshot.recommendation, snapshot.price, check_price,
            )

            check_date = target_date

            results.append(
                BacktestResult(
                    ticker=snapshot.ticker,
                    score_date=snapshot.created_at,
                    recommendation=snapshot.recommendation,
                    price_at_score=snapshot.price,
                    horizon=horizon,
                    price_check_date=check_date,
                    price_at_check=check_price,
                    price_change_pct=round(change_pct, 2),
                    correct=correct,
                )
            )
    return results


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------


def calculate_metrics(results: list[BacktestResult]) -> BacktestMetrics | None:
    """Aggregate backtest results into summary statistics.

    Args:
        results: List of ``BacktestResult`` objects from
            :func:`backtest_snapshots`.

    Returns:
        ``BacktestMetrics`` or ``None`` when the input is empty.
    """
    if not results:
        return None

    total = len(results)
    correct = sum(1 for r in results if r.correct)

    false_positives = sum(
        1 for r in results
        if _is_false_positive(r.recommendation, r.price_change_pct)
    )
    false_negatives = sum(
        1 for r in results
        if _is_false_negative(r.recommendation, r.price_change_pct)
    )

    returns = [r.price_change_pct for r in results]
    avg_return = round(sum(returns) / len(returns), 2) if returns else None

    # Per-(label, horizon) breakdown
    buckets: dict[tuple[str, int], list[float]] = {}
    for r in results:
        key = (r.recommendation, r.horizon)
        buckets.setdefault(key, []).append(r.price_change_pct)

    per_label_horizon: list[LabelHorizonMetrics] = []
    for (label, horizon), rets in sorted(buckets.items()):
        n = len(rets)
        correct_in_bucket = sum(
            1 for r in results
            if r.recommendation == label and r.horizon == horizon and r.correct
        )
        accuracy = round(correct_in_bucket / n * 100, 1) if n > 0 else 0.0
        avg_ret = round(sum(rets) / len(rets), 2) if rets else None
        per_label_horizon.append(
            LabelHorizonMetrics(
                label=label,
                horizon=horizon,
                total=n,
                correct=correct_in_bucket,
                accuracy_pct=accuracy,
                avg_return_pct=avg_ret,
            )
        )

    return BacktestMetrics(
        total_scores=total,
        correct_predictions=correct,
        accuracy_pct=round(correct / total * 100, 1) if total > 0 else 0.0,
        false_positives=false_positives,
        false_negatives=false_negatives,
        avg_return_pct=avg_return,
        by_label_horizon=tuple(per_label_horizon),
        insufficient_data=(total < _MIN_SNAPSHOTS_FOR_REPORT),
    )


# ---------------------------------------------------------------------------
# Report formatting (Telegram / CLI)
# ---------------------------------------------------------------------------


def backtest_report(metrics: BacktestMetrics) -> list[str]:
    """Generate a human-readable backtesting report.

    Args:
        metrics: Aggregate backtesting statistics.

    Returns:
        List of lines ready to be joined with ``\\n``.
    """
    lines: list[str] = [
        "📊 Backtest (сравнение скоров с реальным движением цены)",
        "",
    ]

    if metrics.insufficient_data:
        lines.append(
            f"⚠️ Данных пока мало (всего {metrics.total_scores} проверок). "
            f"Нужно минимум {_MIN_SNAPSHOTS_FOR_REPORT} для осмысленного отчёта."
        )
        lines.append("")
        lines.append("Продолжай сканировать — данные накопятся со временем.")
        lines.append("")
    else:
        lines.append(
            f"Всего проверок: {metrics.total_scores} | "
            f"Верных: {metrics.correct_predictions} "
            f"({metrics.accuracy_pct}%)"
        )
        if metrics.avg_return_pct is not None:
            lines.append(
                f"Средняя доходность на проверку: "
                f"{metrics.avg_return_pct:+.2f}%"
            )
        if metrics.false_positives > 0 or metrics.false_negatives > 0:
            lines.append(
                f"Ложных срабатываний: {metrics.false_positives} | "
                f"Пропусков сигналов: {metrics.false_negatives}"
            )
        lines.append("")

    # Per-(label, horizon) breakdown
    if metrics.by_label_horizon:
        lines.append("По меткам и горизонтам:")
        for item in metrics.by_label_horizon:
            ret = f" | ср.дох. {item.avg_return_pct:+.2f}%" if item.avg_return_pct is not None else ""
            lines.append(
                f"  • {item.label} @ {item.horizon}d: "
                f"{item.accuracy_pct}% ({item.correct}/{item.total}){ret}"
            )
        lines.append("")

    # Overall assessment
    if metrics.total_scores >= _MIN_SNAPSHOTS_FOR_REPORT:
        if metrics.accuracy_pct >= 60:
            lines.append("✓ Точность выше 60% — модель даёт полезный сигнал.")
        elif metrics.accuracy_pct >= 50:
            lines.append("⚠️ Точность около базовой линии (50%). Есть куда расти.")
        else:
            lines.append("⚠️ Точность ниже 50%. Стоит пересмотреть подход.")

    if metrics.total_scores >= _MIN_SNAPSHOTS_FOR_REPORT:
        lines.append("")
    lines.append(
        "⚠️ Важно: это ретроспективная проверка качества скоров, "
        "а не гарантия будущей доходности. "
        "Не является инвестиционной рекомендацией."
    )

    return lines


# ---------------------------------------------------------------------------
# Snapshot-level helper (for /backtest TICKER in Telegram)
# ---------------------------------------------------------------------------


def backtest_snapshot(
    snapshot: AnalysisSnapshot,
    price_at_check: float,
    check_date: datetime | None = None,
    *,
    horizon: int = 5,
) -> BacktestResult:
    """Create a single-horizon backtest result from one snapshot.

    Convenience wrapper for offline tests and the existing callers that pass
    one snapshot at a time.

    Args:
        snapshot: A saved analysis snapshot.
        price_at_check: Price at the check date.
        check_date: When the check price was observed (default: now).
        horizon: Look-ahead horizon in trading days (default 5).

    Returns:
        A ``BacktestResult`` with the given horizon.
    """
    if check_date is None:
        check_date = datetime.now(timezone.utc)

    change_pct = ((price_at_check - snapshot.price) / snapshot.price * 100) if snapshot.price else 0.0
    correct = assess_recommendation_accuracy(
        snapshot.recommendation,
        snapshot.price or 0.0,
        price_at_check,
    )

    return BacktestResult(
        ticker=snapshot.ticker,
        score_date=snapshot.created_at,
        recommendation=snapshot.recommendation,
        price_at_score=snapshot.price or 0.0,
        horizon=horizon,
        price_check_date=check_date,
        price_at_check=price_at_check,
        price_change_pct=round(change_pct, 2),
        correct=correct,
    )


# ---------------------------------------------------------------------------
# Price history fetch (yfinance wrapper for /backtest)
# ---------------------------------------------------------------------------


def fetch_price_history_for_backtest(
    ticker: str,
    earliest_score_date: datetime | None = None,
    timeout_seconds: float = 15,
) -> pd.DataFrame:
    """Download daily price history for backtesting.

    Args:
        ticker: Symbol to download (e.g. ``"AAPL"``).
        earliest_score_date: Fetch from this date minus a buffer.  When
            ``None``, fetches the last 6 months.
        timeout_seconds: yfinance network timeout.

    Returns:
        DataFrame with a DatetimeIndex and columns ``Close``, ``Adj Close``.
        May be empty when the ticker is unknown or the network is down.
    """
    if earliest_score_date is not None:
        start = (earliest_score_date - timedelta(days=_HISTORY_BUFFER_DAYS)).strftime("%Y-%m-%d")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        history = yf.download(
            ticker,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=max(1, int(timeout_seconds)),
        )
    else:
        history = yf.download(
            ticker,
            period="6mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=max(1, int(timeout_seconds)),
        )

    if history is None:
        return pd.DataFrame()
    if isinstance(history.columns, pd.MultiIndex):
        # yfinance returns columns like ('Close', 'AAPL'); flatten.
        try:
            if ticker in history.columns.get_level_values(-1):
                history = history.xs(ticker, axis=1, level=-1, drop_level=True)
            elif ticker in history.columns.get_level_values(0):
                history = history.xs(ticker, axis=1, level=0, drop_level=True)
            else:
                history = history.droplevel(-1, axis=1)
        except Exception:
            pass
    return history if isinstance(history, pd.DataFrame) else pd.DataFrame()
