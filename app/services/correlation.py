"""Portfolio correlation analysis for diversification insights.

Analyzes how stocks in a watchlist move together, helping identify
concentration risk and diversification opportunities.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.services.market_data import get_market_data


@dataclass(frozen=True)
class CorrelationPair:
    """Correlation between two stocks."""

    ticker1: str
    ticker2: str
    correlation: float  # -1.0 to 1.0

    def is_highly_correlated(self, threshold: float = 0.7) -> bool:
        """Check if stocks are highly correlated."""
        return abs(self.correlation) >= threshold

    def is_inversely_correlated(self, threshold: float = -0.6) -> bool:
        """Check if stocks move opposite."""
        return self.correlation <= threshold


@dataclass(frozen=True)
class CorrelationMatrix:
    """Portfolio correlation analysis."""

    tickers: list[str]
    correlations: dict[tuple[str, str], float]  # (ticker1, ticker2) -> correlation
    analysis_date: datetime
    lookback_days: int

    def get_correlation(self, ticker1: str, ticker2: str) -> float | None:
        """Get correlation between two tickers."""
        if ticker1 == ticker2:
            return 1.0
        # Check both orders
        corr = self.correlations.get((min(ticker1, ticker2), max(ticker1, ticker2)))
        return corr

    def high_correlation_pairs(self, threshold: float = 0.7) -> list[CorrelationPair]:
        """Get pairs of stocks that move together."""
        pairs = []
        for (t1, t2), corr in self.correlations.items():
            pair = CorrelationPair(t1, t2, corr)
            if pair.is_highly_correlated(threshold):
                pairs.append(pair)
        return sorted(pairs, key=lambda p: abs(p.correlation), reverse=True)

    def concentration_score(self) -> float:
        """Score portfolio concentration (0-100).

        0 = perfectly diversified (all negative correlations)
        100 = perfectly concentrated (all 1.0 correlations)
        """
        if not self.correlations:
            return 0.0

        avg_correlation = sum(self.correlations.values()) / len(self.correlations)
        # Map -1 to 1 range to 0 to 100 score
        # -1 (perfectly inverse) -> 0
        # 0 (no correlation) -> 50
        # 1 (perfect correlation) -> 100
        return max(0, min(100, (avg_correlation + 1) * 50))


def calculate_correlation_matrix(
    tickers: list[str], lookback_days: int = 90
) -> CorrelationMatrix | None:
    """Calculate correlation matrix for a list of tickers.

    Args:
        tickers: List of stock tickers
        lookback_days: Number of days of historical data to analyze

    Returns:
        CorrelationMatrix with pairwise correlations, or None if data unavailable
    """
    if not tickers or len(tickers) < 2:
        return None

    # Get historical prices for each ticker
    prices_dict = {}
    for ticker in tickers:
        try:
            data = get_market_data(ticker)
            if data and data.price_history:
                # Extract closing prices from history
                # Assuming price_history is list of (date, open, high, low, close, volume)
                prices_dict[ticker] = data.price_history
        except Exception:
            # Skip tickers with data issues
            continue

    if len(prices_dict) < 2:
        return None

    # Align dates and build price matrix
    all_dates = set()
    for history in prices_dict.values():
        for entry in history:
            if isinstance(entry, tuple) and len(entry) >= 5:
                all_dates.add(entry[0])  # date is first element

    if not all_dates:
        return None

    sorted_dates = sorted(all_dates)
    if len(sorted_dates) < 2:
        return None

    # Build price matrix: rows=dates, cols=tickers
    price_matrix = []
    valid_tickers = []

    for ticker in tickers:
        if ticker not in prices_dict:
            continue

        history = prices_dict[ticker]
        prices_by_date = {entry[0]: entry[4] for entry in history if isinstance(entry, tuple) and len(entry) >= 5}

        if len(prices_by_date) < 2:
            continue

        # Collect prices in date order
        ticker_prices = []
        for date in sorted_dates:
            if date in prices_by_date:
                ticker_prices.append(prices_by_date[date])
            else:
                # Use last known price if data missing
                if ticker_prices:
                    ticker_prices.append(ticker_prices[-1])

        if len(ticker_prices) >= len(sorted_dates) * 0.8:  # At least 80% data
            price_matrix.append(ticker_prices)
            valid_tickers.append(ticker)

    if len(valid_tickers) < 2:
        return None

    # Calculate returns instead of prices
    returns_matrix = []
    for prices in price_matrix:
        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] != 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                returns.append(ret)
        returns_matrix.append(returns)

    if not returns_matrix or not returns_matrix[0]:
        return None

    # Calculate correlation matrix using numpy
    returns_array = np.array(returns_matrix)

    try:
        corr_array = np.corrcoef(returns_array)
    except Exception:
        return None

    # Build correlation dict (only upper triangle to avoid duplicates)
    correlations = {}
    for i, ticker1 in enumerate(valid_tickers):
        for j, ticker2 in enumerate(valid_tickers):
            if i < j:
                corr_value = float(corr_array[i, j]) if not np.isnan(corr_array[i, j]) else 0.0
                correlations[(ticker1, ticker2)] = corr_value

    return CorrelationMatrix(
        tickers=valid_tickers,
        correlations=correlations,
        analysis_date=datetime.now(),
        lookback_days=lookback_days,
    )


def correlation_insights(matrix: CorrelationMatrix) -> list[str]:
    """Generate insights from correlation matrix.

    Returns:
        List of human-readable insights
    """
    insights = []

    if not matrix.correlations:
        return insights

    # Concentration score
    conc_score = matrix.concentration_score()
    if conc_score > 80:
        insights.append(
            f"⚠️ Portfolio heavily concentrated ({conc_score:.0f}/100). "
            "Consider adding uncorrelated stocks."
        )
    elif conc_score > 60:
        insights.append(
            f"📊 Portfolio moderately concentrated ({conc_score:.0f}/100). "
            "Some diversification opportunities exist."
        )
    else:
        insights.append(
            f"✓ Portfolio well diversified ({conc_score:.0f}/100). "
            "Good sector/asset mix."
        )

    # High correlation pairs
    high_pairs = matrix.high_correlation_pairs(threshold=0.8)
    if high_pairs:
        if len(high_pairs) == 1:
            pair = high_pairs[0]
            insights.append(
                f"🔗 {pair.ticker1}/{pair.ticker2} move together ({pair.correlation:.2f}). "
                "Consider one if both in portfolio."
            )
        else:
            top_pair = high_pairs[0]
            insights.append(
                f"🔗 Multiple high correlations detected. "
                f"Strongest: {top_pair.ticker1}/{top_pair.ticker2} ({top_pair.correlation:.2f})"
            )

    # Inverse correlation (hedges)
    inverse_pairs = [
        p for p in matrix.correlations.values()
        if p <= -0.5
    ]
    if inverse_pairs:
        insights.append(
            f"🛡️ Found {len(inverse_pairs)} inverse correlations. "
            "These provide natural hedges."
        )

    return insights
