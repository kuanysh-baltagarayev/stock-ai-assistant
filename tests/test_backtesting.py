import unittest
from datetime import datetime, timezone, timedelta

from app.models import AnalysisSnapshot
from app.services.backtesting import (
    BacktestResult,
    BacktestMetrics,
    assess_recommendation_accuracy,
    backtest_snapshot,
    calculate_metrics,
    backtest_report,
)


class AssessRecommendationAccuracyTests(unittest.TestCase):
    def test_buy_correct_price_up(self) -> None:
        correct = assess_recommendation_accuracy("BUY", 100, 105)
        self.assertTrue(correct)

    def test_buy_incorrect_price_down(self) -> None:
        correct = assess_recommendation_accuracy("BUY", 100, 95)
        self.assertFalse(correct)

    def test_sell_correct_price_down(self) -> None:
        correct = assess_recommendation_accuracy("SELL", 100, 95)
        self.assertTrue(correct)

    def test_sell_incorrect_price_up(self) -> None:
        correct = assess_recommendation_accuracy("SELL", 100, 105)
        self.assertFalse(correct)

    def test_hold_correct_minimal_change(self) -> None:
        correct = assess_recommendation_accuracy("HOLD", 100, 101)
        self.assertTrue(correct)

    def test_hold_incorrect_large_change_up(self) -> None:
        correct = assess_recommendation_accuracy("HOLD", 100, 110)
        self.assertFalse(correct)

    def test_hold_incorrect_large_change_down(self) -> None:
        correct = assess_recommendation_accuracy("HOLD", 100, 85)
        self.assertFalse(correct)

    def test_strong_buy(self) -> None:
        correct = assess_recommendation_accuracy("STRONG BUY", 100, 105)
        self.assertTrue(correct)

    def test_strong_sell(self) -> None:
        correct = assess_recommendation_accuracy("STRONG SELL", 100, 95)
        self.assertTrue(correct)

    def test_watch_recommendation(self) -> None:
        # WATCH is treated like HOLD
        correct = assess_recommendation_accuracy("WATCH", 100, 101)
        self.assertTrue(correct)

    def test_zero_price_at_score(self) -> None:
        correct = assess_recommendation_accuracy("BUY", 0, 100)
        self.assertFalse(correct)


class BacktestSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)

    def test_backtest_buy_correct(self) -> None:
        snapshot = AnalysisSnapshot(
            ticker="AAPL",
            price=100,
            recommendation="BUY",
            final_score=70,
            created_at=self.now,
            payload={},
        )
        result = backtest_snapshot(
            snapshot,
            price_at_check=105,
            check_date=self.now + timedelta(days=5),
        )
        self.assertEqual(result.ticker, "AAPL")
        self.assertTrue(result.correct)
        self.assertAlmostEqual(result.price_change_pct, 5.0, places=1)

    def test_backtest_sell_correct(self) -> None:
        snapshot = AnalysisSnapshot(
            ticker="TSLA",
            price=200,
            recommendation="SELL",
            final_score=30,
            created_at=self.now,
            payload={},
        )
        result = backtest_snapshot(
            snapshot,
            price_at_check=190,
            check_date=self.now + timedelta(days=3),
        )
        self.assertTrue(result.correct)
        self.assertAlmostEqual(result.price_change_pct, -5.0, places=1)
        self.assertEqual(result.days_held, 3)

    def test_backtest_days_held(self) -> None:
        snapshot = AnalysisSnapshot(
            ticker="MSFT",
            price=300,
            recommendation="BUY",
            final_score=75,
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            payload={},
        )
        result = backtest_snapshot(
            snapshot,
            price_at_check=315,
            check_date=datetime(2026, 6, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(result.days_held, 10)


class CalculateMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)

    def test_metrics_empty_list(self) -> None:
        metrics = calculate_metrics([])
        self.assertIsNone(metrics)

    def test_metrics_perfect_accuracy(self) -> None:
        results = [
            BacktestResult(
                ticker="AAPL",
                score_date=self.now,
                recommendation="BUY",
                price_at_score=100,
                price_check_date=self.now + timedelta(days=5),
                price_at_check=105,
                price_change_pct=5.0,
                correct=True,
                days_held=5,
            ),
            BacktestResult(
                ticker="MSFT",
                score_date=self.now,
                recommendation="SELL",
                price_at_score=200,
                price_check_date=self.now + timedelta(days=5),
                price_at_check=190,
                price_change_pct=-5.0,
                correct=True,
                days_held=5,
            ),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.total_scores, 2)
        self.assertEqual(metrics.correct_predictions, 2)
        self.assertEqual(metrics.accuracy_pct, 100.0)

    def test_metrics_by_recommendation_type(self) -> None:
        results = [
            BacktestResult("AAPL", self.now, "BUY", 100, self.now + timedelta(days=5), 105, 5.0, True, 5),
            BacktestResult("MSFT", self.now, "BUY", 100, self.now + timedelta(days=5), 95, -5.0, False, 5),
            BacktestResult("GOOGL", self.now, "SELL", 100, self.now + timedelta(days=5), 90, -10.0, True, 5),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.buy_recommendations, 2)
        self.assertEqual(metrics.buy_correct, 1)
        self.assertAlmostEqual(metrics.buy_accuracy_pct, 50.0, places=1)
        self.assertEqual(metrics.sell_recommendations, 1)
        self.assertEqual(metrics.sell_correct, 1)
        self.assertEqual(metrics.sell_accuracy_pct, 100.0)

    def test_metrics_average_days_held(self) -> None:
        results = [
            BacktestResult("AAPL", self.now, "BUY", 100, self.now + timedelta(days=5), 105, 5.0, True, 5),
            BacktestResult("MSFT", self.now, "BUY", 100, self.now + timedelta(days=10), 105, 5.0, True, 10),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertAlmostEqual(metrics.avg_days_held, 7.5, places=1)


class BacktestReportTests(unittest.TestCase):
    def test_report_generation(self) -> None:
        metrics = BacktestMetrics(
            total_scores=100,
            correct_predictions=65,
            accuracy_pct=65.0,
            buy_recommendations=40,
            buy_correct=28,
            buy_accuracy_pct=70.0,
            hold_recommendations=30,
            hold_correct=18,
            hold_accuracy_pct=60.0,
            sell_recommendations=30,
            sell_correct=19,
            sell_accuracy_pct=63.3,
            avg_winning_trade_pct=4.5,
            avg_losing_trade_pct=3.2,
            avg_days_held=7.0,
        )
        report = backtest_report(metrics)
        self.assertGreater(len(report), 0)
        self.assertTrue(any("65.0%" in line for line in report))
        self.assertTrue(any("BUY" in line for line in report))

    def test_report_accuracy_interpretation(self) -> None:
        metrics = BacktestMetrics(
            total_scores=100,
            correct_predictions=45,
            accuracy_pct=45.0,
            buy_recommendations=50,
            buy_correct=23,
            buy_accuracy_pct=46.0,
            hold_recommendations=25,
            hold_correct=11,
            hold_accuracy_pct=44.0,
            sell_recommendations=25,
            sell_correct=11,
            sell_accuracy_pct=44.0,
            avg_winning_trade_pct=2.0,
            avg_losing_trade_pct=2.5,
            avg_days_held=5.0,
        )
        report = backtest_report(metrics)
        # Should include warning about accuracy below 55%
        self.assertTrue(any("below 55%" in line for line in report))


if __name__ == "__main__":
    unittest.main()
