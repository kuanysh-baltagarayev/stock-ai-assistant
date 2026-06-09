import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

from app.services.correlation import (
    CorrelationPair,
    CorrelationMatrix,
    calculate_correlation_matrix,
    correlation_insights,
)


class CorrelationPairTests(unittest.TestCase):
    def test_high_correlation_threshold(self) -> None:
        pair = CorrelationPair("AAPL", "MSFT", 0.75)
        self.assertTrue(pair.is_highly_correlated(threshold=0.7))
        self.assertFalse(pair.is_highly_correlated(threshold=0.8))

    def test_inverse_correlation(self) -> None:
        pair = CorrelationPair("AAPL", "GLD", -0.65)
        self.assertTrue(pair.is_inversely_correlated(threshold=-0.6))
        self.assertFalse(pair.is_inversely_correlated(threshold=-0.7))

    def test_perfect_correlation(self) -> None:
        pair = CorrelationPair("AAPL", "AAPL", 1.0)
        self.assertTrue(pair.is_highly_correlated(threshold=0.9))

    def test_perfect_inverse(self) -> None:
        pair = CorrelationPair("AAPL", "GLD", -1.0)
        self.assertTrue(pair.is_inversely_correlated(threshold=-0.99))


class CorrelationMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tickers = ["AAPL", "MSFT", "GOOGL", "AMZN"]
        self.correlations = {
            ("AAPL", "MSFT"): 0.85,
            ("AAPL", "GOOGL"): 0.72,
            ("AAPL", "AMZN"): 0.65,
            ("MSFT", "GOOGL"): 0.78,
            ("MSFT", "AMZN"): 0.68,
            ("GOOGL", "AMZN"): 0.62,
        }
        self.matrix = CorrelationMatrix(
            tickers=self.tickers,
            correlations=self.correlations,
            analysis_date=datetime.now(),
            lookback_days=90,
        )

    def test_get_correlation_same_ticker(self) -> None:
        corr = self.matrix.get_correlation("AAPL", "AAPL")
        self.assertEqual(corr, 1.0)

    def test_get_correlation_different_tickers(self) -> None:
        corr = self.matrix.get_correlation("AAPL", "MSFT")
        self.assertEqual(corr, 0.85)

    def test_high_correlation_pairs(self) -> None:
        pairs = self.matrix.high_correlation_pairs(threshold=0.7)
        # We have 3 pairs stored (upper triangle only to avoid duplicates)
        self.assertEqual(len(pairs), 3)
        # Sorted by correlation (highest first)
        self.assertEqual(pairs[0].ticker1, "AAPL")
        self.assertEqual(pairs[0].ticker2, "MSFT")
        self.assertEqual(pairs[0].correlation, 0.85)

    def test_concentration_score(self) -> None:
        score = self.matrix.concentration_score()
        # Average correlation is (0.85+0.72+0.65+0.78+0.68+0.62)/6 = 0.717
        # Score = (0.717 + 1) * 50 = 85.85
        self.assertGreater(score, 80)
        self.assertLess(score, 90)

    def test_concentration_score_low(self) -> None:
        # Matrix with low correlations
        low_corr_matrix = CorrelationMatrix(
            tickers=["AAPL", "TLT", "GLD"],
            correlations={
                ("AAPL", "TLT"): -0.3,
                ("AAPL", "GLD"): 0.1,
                ("TLT", "GLD"): 0.2,
            },
            analysis_date=datetime.now(),
            lookback_days=90,
        )
        score = low_corr_matrix.concentration_score()
        # Average = (-0.3+0.1+0.2)/3 = 0
        # Score = (0 + 1) * 50 = 50
        self.assertAlmostEqual(score, 50, delta=5)

    def test_empty_correlations(self) -> None:
        empty_matrix = CorrelationMatrix(
            tickers=["AAPL"],
            correlations={},
            analysis_date=datetime.now(),
            lookback_days=90,
        )
        score = empty_matrix.concentration_score()
        self.assertEqual(score, 0.0)


class CorrelationCalculationTests(unittest.TestCase):
    def test_calculate_with_insufficient_tickers(self) -> None:
        result = calculate_correlation_matrix(["AAPL"])
        self.assertIsNone(result)

    def test_calculate_with_empty_list(self) -> None:
        result = calculate_correlation_matrix([])
        self.assertIsNone(result)

    @patch("app.services.correlation.get_market_data")
    def test_calculate_with_mock_data(self, mock_get: patch) -> None:
        # Mock market data for two stocks — return dicts matching get_market_data() contract
        dates = pd.date_range("2026-01-01", periods=5, freq="D")
        aapl_df = pd.DataFrame({
            "Open": [150, 150.5, 151.5, 152, 153.5],
            "High": [151, 152, 153, 154, 155],
            "Low": [149, 150, 151, 152, 153],
            "Close": [150.5, 151.5, 152.0, 153.5, 154.0],
            "Volume": [1_000_000, 1_100_000, 1_200_000, 1_300_000, 1_400_000],
        }, index=dates)
        msft_df = pd.DataFrame({
            "Open": [300, 300.5, 301.5, 302, 303.5],
            "High": [301, 302, 303, 304, 305],
            "Low": [299, 300, 301, 302, 303],
            "Close": [300.5, 301.5, 302.0, 303.5, 304.0],
            "Volume": [2_000_000, 2_100_000, 2_200_000, 2_300_000, 2_400_000],
        }, index=dates)

        def mock_get_side_effect(ticker: str):
            if ticker == "AAPL":
                return {"history": aapl_df}
            elif ticker == "MSFT":
                return {"history": msft_df}
            else:
                return None

        mock_get.side_effect = mock_get_side_effect

        result = calculate_correlation_matrix(["AAPL", "MSFT"], lookback_days=90)
        self.assertIsNotNone(result)
        self.assertEqual(len(result.tickers), 2)
        # These stocks with similar returns should have positive correlation
        corr = result.get_correlation("AAPL", "MSFT")
        self.assertIsNotNone(corr)
        self.assertGreater(corr, 0.8)  # Very similar returns


class CorrelationInsightsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tickers = ["AAPL", "MSFT", "GOOGL"]

    def test_insights_concentrated_portfolio(self) -> None:
        matrix = CorrelationMatrix(
            tickers=self.tickers,
            correlations={
                ("AAPL", "MSFT"): 0.95,
                ("AAPL", "GOOGL"): 0.92,
                ("MSFT", "GOOGL"): 0.93,
            },
            analysis_date=datetime.now(),
            lookback_days=90,
        )
        insights = correlation_insights(matrix)
        self.assertTrue(any("concentrated" in insight.lower() for insight in insights))

    def test_insights_diversified_portfolio(self) -> None:
        matrix = CorrelationMatrix(
            tickers=self.tickers,
            correlations={
                ("AAPL", "TLT"): -0.2,
                ("AAPL", "GLD"): 0.1,
                ("TLT", "GLD"): 0.15,
            },
            analysis_date=datetime.now(),
            lookback_days=90,
        )
        insights = correlation_insights(matrix)
        self.assertTrue(any("diversified" in insight.lower() for insight in insights))

    def test_insights_high_correlations(self) -> None:
        matrix = CorrelationMatrix(
            tickers=["AAPL", "MSFT"],
            correlations={
                ("AAPL", "MSFT"): 0.85,
            },
            analysis_date=datetime.now(),
            lookback_days=90,
        )
        insights = correlation_insights(matrix)
        self.assertTrue(any("together" in insight.lower() for insight in insights))

    def test_insights_empty_correlations(self) -> None:
        matrix = CorrelationMatrix(
            tickers=["AAPL"],
            correlations={},
            analysis_date=datetime.now(),
            lookback_days=90,
        )
        insights = correlation_insights(matrix)
        # Empty correlations returns no insights (can't calculate concentration)
        self.assertEqual(len(insights), 0)


if __name__ == "__main__":
    unittest.main()
