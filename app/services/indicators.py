import numpy as np
import pandas as pd

from app.schemas import TechnicalIndicators


TRADING_DAYS_PER_YEAR = 252


def calculate_indicators(history: pd.DataFrame) -> TechnicalIndicators:
    close = history["Close"].dropna().astype(float)
    if close.empty:
        return TechnicalIndicators()

    return TechnicalIndicators(
        change_1d_pct=_percentage_change(close, 1),
        change_1m_pct=_percentage_change(close, 21),
        change_6m_pct=_percentage_change(close, 126),
        moving_average_50=_moving_average(close, 50),
        moving_average_200=_moving_average(close, 200),
        rsi=_rsi(close),
        volatility_pct=_annualized_volatility(close),
        max_drawdown_pct=_max_drawdown(close),
    )


def _percentage_change(close: pd.Series, periods: int) -> float | None:
    if len(close) <= periods:
        return None
    previous = close.iloc[-periods - 1]
    current = close.iloc[-1]
    if previous == 0:
        return None
    return round(((current / previous) - 1) * 100, 2)


def _moving_average(close: pd.Series, window: int) -> float | None:
    if len(close) < window:
        return None
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
    returns = np.log(close / close.shift(1)).dropna()
    if returns.empty:
        return None
    volatility = returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100
    return round(float(volatility), 2)


def _max_drawdown(close: pd.Series) -> float | None:
    if close.empty:
        return None
    rolling_max = close.cummax()
    drawdown = (close / rolling_max - 1) * 100
    return round(float(drawdown.min()), 2)
