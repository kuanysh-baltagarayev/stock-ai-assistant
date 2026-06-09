import numpy as np
import pandas as pd

from app.schemas import TechnicalIndicators


TRADING_DAYS_PER_YEAR = 252

# NOTE: this module consumes raw-close prices (no auto-adjustment) from
# yfinance. Splits and dividends are NOT baked into the series, which
# means percentage changes, moving averages, RSI, and volatility are
# computed on discontinuous data when corporate actions are present.
# The caller (market_data) flags split_detected/dividend_detected so
# Telegram can warn users. If the history has already been adjusted
# upstream (auto_adjust=True), results are comparable but the data
# quality flag layer still reports raw-close behaviour from provenance.


def calculate_indicators(history: pd.DataFrame) -> TechnicalIndicators:
    close = history["Close"].dropna().astype(float)
    if close.empty:
        return TechnicalIndicators()

    macd_line, macd_signal, macd_histogram = _macd(close)
    volume_avg_21d, volume_recent_ratio = _volume_analysis(history)

    return TechnicalIndicators(
        change_1d_pct=_percentage_change(close, 1),
        change_1m_pct=_percentage_change(close, 21),
        change_6m_pct=_percentage_change(close, 126),
        moving_average_50=_moving_average(close, 50),
        moving_average_200=_moving_average(close, 200),
        rsi=_rsi(close),
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_histogram=macd_histogram,
        volume_avg_21d=volume_avg_21d,
        volume_recent_ratio=volume_recent_ratio,
        volatility_pct=_annualized_volatility(close),
        max_drawdown_pct=_max_drawdown(close),
    )


def _percentage_change(close: pd.Series, periods: int) -> float | None:
    if len(close) <= periods:
        # When exact lookback is unavailable but we have at least half the
        # needed data, compute an estimated change over the available window.
        if len(close) < max(5, periods // 2):
            return None
        available = len(close)
        if available < 2:
            return None
        previous = close.iloc[-available]
        current = close.iloc[-1]
        if previous == 0:
            return None
        return round(((current / previous) - 1) * 100, 2)
    previous = close.iloc[-periods - 1]
    current = close.iloc[-1]
    if previous == 0:
        return None
    return round(((current / previous) - 1) * 100, 2)


def _moving_average(close: pd.Series, window: int) -> float | None:
    if len(close) < window:
        # When exact window is unavailable but we have at least 60% of the
        # data, compute an estimated MA.  The caller can tag this as
        # "estimated" via the TechnicalIndicators data quality layer.
        # Returns None when too little data for any meaningful estimate.
        if len(close) < max(30, window // 2):
            return None
        available = len(close)
        avg = float(close.rolling(window=available).mean().iloc[-1])
        return round(avg, 2)
    return round(float(close.rolling(window=window).mean().iloc[-1]), 2)


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) <= period:
        return None

    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    average_gain = gains.rolling(window=period).mean().iloc[-1]
    average_loss = losses.rolling(window=period).mean().iloc[-1]
    if pd.isna(average_gain) or pd.isna(average_loss):
        return None
    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss
    rsi = 100 - (100 / (1 + relative_strength))
    return round(float(rsi), 2)


def _annualized_volatility(close: pd.Series) -> float | None:
    if len(close) < 2:
        return None
    returns = np.log(close / close.shift(1))
    # Remove NaN and infinite values (infinite log-returns arise from
    # zero or negative close prices, e.g. from corporate actions or bad data).
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 2:
        return None
    volatility = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    return round(float(volatility), 2)


def _max_drawdown(close: pd.Series) -> float | None:
    if close.empty:
        return None
    rolling_max = close.cummax()
    drawdown = (close / rolling_max - 1) * 100
    return round(float(drawdown.min()), 2)


def _macd(
    close: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[float | None, float | None, float | None]:
    """Compute MACD line, signal line, and histogram.

    Returns (macd_line, macd_signal, macd_histogram) for the most recent
    trading day, or (None, None, None) when insufficient data exists.
    """
    if len(close) < slow_period + signal_period:
        return None, None, None

    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=signal_period, adjust=False).mean()
    histogram = macd - signal

    return (
        round(float(macd.iloc[-1]), 4),
        round(float(signal.iloc[-1]), 4),
        round(float(histogram.iloc[-1]), 4),
    )


def _volume_analysis(
    history: pd.DataFrame,
    window: int = 21,
) -> tuple[float | None, float | None]:
    """Compute average volume and recent-to-average ratio.

    Returns (volume_avg_21d, volume_recent_ratio) or (None, None) when
    the history lacks a Volume column or has insufficient data.
    """
    if "Volume" not in history.columns:
        return None, None

    volume = history["Volume"].dropna().astype(float)
    if len(volume) < window:
        return None, None

    avg = float(volume.iloc[-window:].mean())
    recent = float(volume.iloc[-1])

    if avg <= 0:
        return None, None

    return round(avg, 0), round(recent / avg, 2)
