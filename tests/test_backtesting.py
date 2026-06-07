from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from app.models import AnalysisSnapshot
from app.services.backtesting import (
    DEFAULT_HORIZONS,
    BacktestMetrics,
    BacktestResult,
    LabelHorizonMetrics,
    _is_false_negative,
    _is_false_positive,
    _lookup_close_price,
    assess_recommendation_accuracy,
    backtest_report,
    backtest_snapshot,
    backtest_snapshots,
    calculate_metrics,
    fetch_price_history_for_backtest,
)


# ---------------------------------------------------------------------------
# Label-based accuracy assessment
# ---------------------------------------------------------------------------


class AssessRecommendationAccuracyTests(unittest.TestCase):
    """Tests for assess_recommendation_accuracy with current research labels."""

    def test_high_interest_correct_price_up(self) -> None:
        self.assertTrue(assess_recommendation_accuracy("HIGH_INTEREST", 100, 105))

    def test_high_interest_incorrect_price_down(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("HIGH_INTEREST", 100, 95))

    def test_watch_correct_price_up(self) -> None:
        self.assertTrue(assess_recommendation_accuracy("WATCH", 100, 101))

    def test_watch_incorrect_price_down(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("WATCH", 100, 99))

    def test_neutral_correct_no_change(self) -> None:
        self.assertTrue(assess_recommendation_accuracy("NEUTRAL", 100, 100))

    def test_neutral_correct_small_fluctuation(self) -> None:
        self.assertTrue(assess_recommendation_accuracy("NEUTRAL", 100, 101))

    def test_neutral_incorrect_large_up(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("NEUTRAL", 100, 110))

    def test_neutral_incorrect_large_down(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("NEUTRAL", 100, 85))

    def test_caution_correct_price_down(self) -> None:
        self.assertTrue(assess_recommendation_accuracy("CAUTION", 100, 95))

    def test_caution_incorrect_price_up(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("CAUTION", 100, 105))

    def test_high_risk_correct_price_down(self) -> None:
        self.assertTrue(assess_recommendation_accuracy("HIGH_RISK", 100, 90))

    def test_high_risk_incorrect_price_up(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("HIGH_RISK", 100, 110))

    def test_zero_price_returns_false(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("HIGH_INTEREST", 0, 100))

    def test_unknown_label_returns_false(self) -> None:
        self.assertFalse(assess_recommendation_accuracy("UNKNOWN", 100, 105))


class FalsePositiveNegativeTests(unittest.TestCase):
    """Tests for _is_false_positive and _is_false_negative."""

    def test_high_interest_false_positive_price_drops_sharply(self) -> None:
        self.assertTrue(_is_false_positive("HIGH_INTEREST", -5.0))

    def test_high_interest_not_false_positive_small_dip(self) -> None:
        self.assertFalse(_is_false_positive("HIGH_INTEREST", -1.0))

    def test_caution_false_positive_price_jumps(self) -> None:
        self.assertTrue(_is_false_positive("CAUTION", 5.0))

    def test_high_risk_false_positive_price_jumps(self) -> None:
        self.assertTrue(_is_false_positive("HIGH_RISK", 5.0))

    def test_neutral_not_false_positive(self) -> None:
        # Neutral labels are not classified as false positives
        self.assertFalse(_is_false_positive("NEUTRAL", 5.0))

    def test_neutral_false_negative_large_move(self) -> None:
        self.assertTrue(_is_false_negative("NEUTRAL", 5.0))

    def test_neutral_not_false_negative_small_move(self) -> None:
        self.assertFalse(_is_false_negative("NEUTRAL", 1.0))

    def test_bullish_not_false_negative(self) -> None:
        self.assertFalse(_is_false_negative("HIGH_INTEREST", 5.0))

    def test_bearish_not_false_negative(self) -> None:
        self.assertFalse(_is_false_negative("CAUTION", -5.0))


# ---------------------------------------------------------------------------
# Price lookup helper
# ---------------------------------------------------------------------------


class LookupClosePriceTests(unittest.TestCase):
    """Tests for _lookup_close_price with various DataFrame structures."""

    def setUp(self) -> None:
        dates = pd.date_range("2026-06-01", "2026-06-10", freq="D")
        self._history = pd.DataFrame(
            {"Close": [150 + i for i in range(len(dates))]},
            index=dates,
        )

    def test_exact_date_found(self) -> None:
        price = _lookup_close_price(
            self._history,
            datetime(2026, 6, 3, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(price)
        self.assertAlmostEqual(price, 152.0)  # 150 + 2

    def test_date_before_history(self) -> None:
        # May 25 is 7 days before June 1; the lookup searches 10 days forward
        # and finds June 1 → price=150.0.
        price = _lookup_close_price(
            self._history,
            datetime(2026, 5, 25, tzinfo=timezone.utc),
        )
        self.assertAlmostEqual(price, 150.0)  # first row in history

    def test_date_well_before_history(self) -> None:
        # More than 10 days before the first entry → None.
        price = _lookup_close_price(
            self._history,
            datetime(2026, 5, 15, tzinfo=timezone.utc),
        )
        self.assertIsNone(price)

    def test_empty_history(self) -> None:
        price = _lookup_close_price(pd.DataFrame(), datetime.now(timezone.utc))
        self.assertIsNone(price)

    def test_missing_close_column(self) -> None:
        df = pd.DataFrame({"Open": [100, 101]}, index=pd.date_range("2026-06-01", periods=2))
        price = _lookup_close_price(df, datetime(2026, 6, 1, tzinfo=timezone.utc))
        self.assertIsNone(price)

    def test_adj_close_column(self) -> None:
        dates = pd.date_range("2026-06-01", "2026-06-05", freq="D")
        df = pd.DataFrame(
            {"Adj Close": [100.0, 101.0, 102.0, 103.0, 104.0]},
            index=dates,
        )
        price = _lookup_close_price(
            df,
            datetime(2026, 6, 3, tzinfo=timezone.utc),
        )
        self.assertAlmostEqual(price, 102.0)

    def test_none_history(self) -> None:
        price = _lookup_close_price(None, datetime.now(timezone.utc))
        self.assertIsNone(price)


# ---------------------------------------------------------------------------
# Multi-snapshot backtesting
# ---------------------------------------------------------------------------


class BacktestSnapshotsTests(unittest.TestCase):
    """Tests for backtest_snapshots with a price DataFrame."""

    def setUp(self) -> None:
        self.now = datetime(2026, 6, 5, tzinfo=timezone.utc)
        dates = pd.date_range("2026-05-01", "2026-06-20", freq="D")
        self._history = pd.DataFrame(
            {"Close": [float(100 + i) for i in range(len(dates))]},
            index=dates,
        )
        self._snapshots = [
            AnalysisSnapshot(
                id=1, ticker="TEST", price=100.0, recommendation="HIGH_INTEREST",
                final_score=80.0, payload={},
                created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
            ),
            AnalysisSnapshot(
                id=2, ticker="TEST", price=110.0, recommendation="CAUTION",
                final_score=40.0, payload={},
                created_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            ),
        ]

    def test_backtest_bullish_correct(self) -> None:
        """HIGH_INTEREST when price goes up → correct."""
        results = backtest_snapshots(self._snapshots, self._history, horizons=(5,))
        # First snapshot: price=100 on May 10, check ~May 17 → price ~117
        self.assertGreater(len(results), 0)
        self.assertTrue(results[0].correct)
        self.assertEqual(results[0].horizon, 5)

    def test_backtest_bearish_correct(self) -> None:
        """CAUTION when price goes down → correct."""
        results = backtest_snapshots(self._snapshots, self._history, horizons=(5,))
        self.assertGreater(len(results), 1)
        # May 15 price=110, check May 22 → price ~122 (up, so CAUTION is wrong)
        self.assertTrue(any(r.recommendation == "CAUTION" for r in results))
        caution_results = [r for r in results if r.recommendation == "CAUTION"]
        self.assertFalse(caution_results[0].correct)

    def test_empty_snapshots(self) -> None:
        results = backtest_snapshots([], self._history)
        self.assertEqual(len(results), 0)

    def test_snapshot_without_price_skipped(self) -> None:
        snapshots = [
            AnalysisSnapshot(
                id=3, ticker="TEST", price=None, recommendation="NEUTRAL",
                final_score=50.0, payload={},
                created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
            ),
        ]
        results = backtest_snapshots(snapshots, self._history)
        self.assertEqual(len(results), 0)

    def test_snapshot_with_price_zero_skipped(self) -> None:
        snapshots = [
            AnalysisSnapshot(
                id=4, ticker="TEST", price=0.0, recommendation="NEUTRAL",
                final_score=50.0, payload={},
                created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
            ),
        ]
        results = backtest_snapshots(snapshots, self._history)
        self.assertEqual(len(results), 0)

    def test_multi_horizon_returns_multiple_results(self) -> None:
        results = backtest_snapshots(
            self._snapshots, self._history, horizons=(1, 5, 20),
        )
        # 2 snapshots × 3 horizons = 6 results max, but some lookups may miss
        self.assertGreaterEqual(len(results), 4)

    def test_all_horizons_in_results(self) -> None:
        results = backtest_snapshots(
            self._snapshots, self._history, horizons=(1, 5, 20),
        )
        horizons_found = {r.horizon for r in results}
        for h in (1, 5, 20):
            self.assertIn(h, horizons_found)


class BacktestSnapshotSingleTests(unittest.TestCase):
    """Tests for the single-snapshot convenience wrapper."""

    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)

    def test_backtest_buy_correct(self) -> None:
        snapshot = AnalysisSnapshot(
            ticker="AAPL", price=100, recommendation="HIGH_INTEREST",
            final_score=70, created_at=self.now, payload={},
        )
        result = backtest_snapshot(
            snapshot,
            price_at_check=105,
            check_date=self.now + timedelta(days=5),
        )
        self.assertEqual(result.ticker, "AAPL")
        self.assertTrue(result.correct)
        self.assertAlmostEqual(result.price_change_pct, 5.0, places=1)
        self.assertEqual(result.horizon, 5)

    def test_backtest_sell_correct(self) -> None:
        snapshot = AnalysisSnapshot(
            ticker="TSLA", price=200, recommendation="HIGH_RISK",
            final_score=30, created_at=self.now, payload={},
        )
        result = backtest_snapshot(
            snapshot,
            price_at_check=190,
            check_date=self.now + timedelta(days=3),
        )
        self.assertTrue(result.correct)
        self.assertAlmostEqual(result.price_change_pct, -5.0, places=1)

    def test_backtest_with_custom_horizon(self) -> None:
        snapshot = AnalysisSnapshot(
            ticker="MSFT", price=300, recommendation="HIGH_INTEREST",
            final_score=75,
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            payload={},
        )
        result = backtest_snapshot(
            snapshot,
            price_at_check=315,
            check_date=datetime(2026, 6, 11, tzinfo=timezone.utc),
            horizon=10,
        )
        self.assertEqual(result.horizon, 10)


class CalculateMetricsTests(unittest.TestCase):
    """Tests for aggregate metrics calculation."""

    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)

    def test_empty_list_returns_none(self) -> None:
        self.assertIsNone(calculate_metrics([]))

    def test_perfect_accuracy(self) -> None:
        results = [
            BacktestResult(
                ticker="AAPL", score_date=self.now, recommendation="HIGH_INTEREST",
                price_at_score=100, horizon=5, price_check_date=self.now,
                price_at_check=105, price_change_pct=5.0, correct=True,
            ),
            BacktestResult(
                ticker="MSFT", score_date=self.now, recommendation="CAUTION",
                price_at_score=200, horizon=5, price_check_date=self.now,
                price_at_check=190, price_change_pct=-5.0, correct=True,
            ),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.total_scores, 2)
        self.assertEqual(metrics.correct_predictions, 2)
        self.assertEqual(metrics.accuracy_pct, 100.0)

    def test_false_positives_counted(self) -> None:
        results = [
            BacktestResult(
                ticker="AAPL", score_date=self.now, recommendation="HIGH_INTEREST",
                price_at_score=100, horizon=5, price_check_date=self.now,
                price_at_check=90, price_change_pct=-10.0, correct=False,
            ),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.false_positives, 1)

    def test_false_negatives_counted(self) -> None:
        results = [
            BacktestResult(
                ticker="AAPL", score_date=self.now, recommendation="NEUTRAL",
                price_at_score=100, horizon=5, price_check_date=self.now,
                price_at_check=120, price_change_pct=20.0, correct=False,
            ),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.false_negatives, 1)

    def test_insufficient_data_flag(self) -> None:
        results = [
            BacktestResult(
                ticker="AAPL", score_date=self.now, recommendation="HIGH_INTEREST",
                price_at_score=100, horizon=5, price_check_date=self.now,
                price_at_check=105, price_change_pct=5.0, correct=True,
            ),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertTrue(metrics.insufficient_data)

    def test_by_label_horizon_breakdown(self) -> None:
        results = [
            BacktestResult(
                ticker="AAPL", score_date=self.now, recommendation="HIGH_INTEREST",
                price_at_score=100, horizon=5, price_check_date=self.now,
                price_at_check=105, price_change_pct=5.0, correct=True,
            ),
            BacktestResult(
                ticker="AAPL", score_date=self.now, recommendation="HIGH_INTEREST",
                price_at_score=100, horizon=20, price_check_date=self.now,
                price_at_check=110, price_change_pct=10.0, correct=True,
            ),
            BacktestResult(
                ticker="MSFT", score_date=self.now, recommendation="CAUTION",
                price_at_score=200, horizon=5, price_check_date=self.now,
                price_at_check=195, price_change_pct=-2.5, correct=True,
            ),
        ]
        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertEqual(len(metrics.by_label_horizon), 3)  # 3 unique (label, horizon)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class BacktestReportTests(unittest.TestCase):
    """Tests for backtest_report output."""

    def _assert_disclaimer(self, full: str) -> None:
        self.assertIn("не является инвестиционной", full.lower())

    def test_sufficient_data_report(self) -> None:
        metrics = BacktestMetrics(
            total_scores=20,
            correct_predictions=14,
            accuracy_pct=70.0,
            false_positives=2,
            false_negatives=1,
            avg_return_pct=2.5,
            by_label_horizon=(
                LabelHorizonMetrics(
                    label="HIGH_INTEREST", horizon=5, total=10,
                    correct=7, accuracy_pct=70.0, avg_return_pct=3.0,
                ),
            ),
            insufficient_data=False,
        )
        report = backtest_report(metrics)
        full = "\n".join(report)
        self.assertIn("70.0%", full)
        self.assertIn("HIGH_INTEREST", full)
        self.assertIn("@ 5d", full)
        self._assert_disclaimer(full)
        self.assertIn("70.0%", full)
        self.assertIn("2.5", full)

    def test_insufficient_data_report(self) -> None:
        metrics = BacktestMetrics(
            total_scores=2,
            correct_predictions=2,
            accuracy_pct=100.0,
            false_positives=0,
            false_negatives=0,
            avg_return_pct=5.0,
            by_label_horizon=(),
            insufficient_data=True,
        )
        report = backtest_report(metrics)
        full = "\n".join(report)
        self.assertIn("Данных пока мало", full)
        self._assert_disclaimer(full)

    def test_below_50_pct_warning(self) -> None:
        metrics = BacktestMetrics(
            total_scores=10,
            correct_predictions=3,
            accuracy_pct=30.0,
            false_positives=2,
            false_negatives=3,
            avg_return_pct=-1.0,
            by_label_horizon=(),
            insufficient_data=False,
        )
        report = backtest_report(metrics)
        full = "\n".join(report)
        self.assertIn("ниже 50%", full)

    def test_disclaimer_always_present(self) -> None:
        metrics = BacktestMetrics(
            total_scores=10, correct_predictions=5, accuracy_pct=50.0,
            false_positives=0, false_negatives=0, avg_return_pct=0.0,
            by_label_horizon=(), insufficient_data=False,
        )
        report = backtest_report(metrics)
        full = "\n".join(report)
        self._assert_disclaimer(full)

    def test_report_mentions_horizons(self) -> None:
        metrics = BacktestMetrics(
            total_scores=15, correct_predictions=9, accuracy_pct=60.0,
            false_positives=1, false_negatives=1, avg_return_pct=1.5,
            by_label_horizon=(
                LabelHorizonMetrics(
                    label="HIGH_INTEREST", horizon=5, total=8,
                    correct=5, accuracy_pct=62.5, avg_return_pct=2.0,
                ),
                LabelHorizonMetrics(
                    label="CAUTION", horizon=1, total=7,
                    correct=4, accuracy_pct=57.1, avg_return_pct=-1.0,
                ),
            ),
            insufficient_data=False,
        )
        report = backtest_report(metrics)
        full = "\n".join(report)
        self.assertIn("@ 5d", full)
        self.assertIn("@ 1d", full)


# ---------------------------------------------------------------------------
# Price history fetch (mocked)
# ---------------------------------------------------------------------------


class FetchPriceHistoryForBacktestTests(unittest.TestCase):
    """Tests for fetch_price_history_for_backtest (mocked yfinance)."""

    @patch("app.services.backtesting.yf.download")
    def test_without_earliest_date_uses_6mo(self, mock_download: MagicMock) -> None:
        mock_download.return_value = MagicMock(spec=pd.DataFrame)
        mock_download.return_value.empty = False
        mock_download.return_value.columns = ["Close", "Adj Close"]
        df = fetch_price_history_for_backtest("AAPL")
        self.assertIsNotNone(df)
        mock_download.assert_called_once()
        _, kwargs = mock_download.call_args
        self.assertEqual(kwargs.get("period"), "6mo")

    @patch("app.services.backtesting.yf.download")
    def test_with_earliest_date_uses_start_end(self, mock_download: MagicMock) -> None:
        mock_download.return_value = MagicMock(spec=pd.DataFrame)
        mock_download.return_value.empty = False
        mock_download.return_value.columns = ["Close", "Adj Close"]
        earliest = datetime(2026, 5, 1, tzinfo=timezone.utc)
        df = fetch_price_history_for_backtest("MSFT", earliest)
        self.assertIsNotNone(df)
        _, kwargs = mock_download.call_args
        self.assertIn("start", kwargs)
        self.assertIn("end", kwargs)

    @patch("app.services.backtesting.yf.download")
    def test_multindex_columns_flattened(self, mock_download: MagicMock) -> None:
        idx = pd.date_range("2026-06-01", "2026-06-05", freq="D")
        multi = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Volume", "AAPL")])
        mock_df = pd.DataFrame(
            [[150, 1000], [151, 1100], [152, 1200], [153, 1300], [154, 1400]],
            index=idx,
            columns=multi,
        )
        mock_download.return_value = mock_df
        df = fetch_price_history_for_backtest("AAPL")
        self.assertIsNotNone(df)
        self.assertFalse(isinstance(df.columns, pd.MultiIndex))

    @patch("app.services.backtesting.yf.download")
    def test_none_return_handled(self, mock_download: MagicMock) -> None:
        mock_download.return_value = None
        df = fetch_price_history_for_backtest("BOGUS")
        self.assertTrue(df.empty)


# ---------------------------------------------------------------------------
# Telegram integration (backtest text output)
# ---------------------------------------------------------------------------


class BacktestTelegramTests(unittest.TestCase):
    """Integration tests: /backtest produces the right output."""

    _FORBIDDEN = ("покупать", "продавать")

    def test_backtest_with_no_snapshots(self) -> None:
        from app.services.runtime_budget import reset_runtime_budgets
        from app.services.telegram_bot import TelegramBotService

        reset_runtime_budgets()
        service = TelegramBotService(settings=SimpleNamespace())

        with patch("app.services.telegram_bot.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.query.return_value.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
            mock_session_local.return_value = mock_db
            text = service._backtest_ticker("NODATA")
            self.assertIn("Нет анализов", text)
            self.assertIn("NODATA", text)

    def test_backtest_with_snapshots_and_history(self) -> None:
        now = datetime(2026, 6, 8, tzinfo=timezone.utc)
        snapshots = [
            AnalysisSnapshot(
                id=1, ticker="AAPL", price=150, recommendation="HIGH_INTEREST",
                final_score=80, payload={},
                created_at=now - timedelta(days=10),
            ),
            AnalysisSnapshot(
                id=2, ticker="AAPL", price=155, recommendation="HIGH_INTEREST",
                final_score=75, payload={},
                created_at=now - timedelta(days=5),
            ),
            AnalysisSnapshot(
                id=3, ticker="AAPL", price=148, recommendation="NEUTRAL",
                final_score=55, payload={},
                created_at=now - timedelta(days=3),
            ),
            AnalysisSnapshot(
                id=4, ticker="AAPL", price=160, recommendation="CAUTION",
                final_score=40, payload={},
                created_at=now - timedelta(days=1),
            ),
        ]

        dates = pd.date_range("2026-05-25", "2026-06-20", freq="D")
        history = pd.DataFrame(
            {"Close": [float(140 + i * 0.3) for i in range(len(dates))]},
            index=dates,
        )

        from app.services.backtesting import (
            backtest_snapshots,
            calculate_metrics,
            backtest_report,
        )

        results = backtest_snapshots(snapshots, history, horizons=(1, 5))
        self.assertGreater(len(results), 0)

        metrics = calculate_metrics(results)
        self.assertIsNotNone(metrics)
        self.assertFalse(metrics.insufficient_data)

        report = backtest_report(metrics)
        full = "\n".join(report)
        self.assertIn("не является инвестиционной", full.lower())

        # No buy/sell wording
        lower = full.lower()
        for word in self._FORBIDDEN:
            if f" {word} " in f" {lower} " or lower.startswith(f"{word} ") or lower.endswith(f" {word}"):
                self.fail(f"Report contains forbidden word '{word}': {full}")

    def test_backtest_output_no_buy_sell(self) -> None:
        """Verify that backtest_report content does not use buy/sell wording."""
        metrics = BacktestMetrics(
            total_scores=10, correct_predictions=6, accuracy_pct=60.0,
            false_positives=1, false_negatives=1, avg_return_pct=1.0,
            by_label_horizon=(
                LabelHorizonMetrics(
                    label="HIGH_INTEREST", horizon=5, total=5,
                    correct=3, accuracy_pct=60.0, avg_return_pct=2.0,
                ),
                LabelHorizonMetrics(
                    label="CAUTION", horizon=5, total=5,
                    correct=3, accuracy_pct=60.0, avg_return_pct=-0.5,
                ),
            ),
            insufficient_data=False,
        )
        report = backtest_report(metrics)
        full = "\n".join(report)
        lower = full.lower()
        for word in ("покупать", "продавать", "buy", "sell"):
            if f" {word} " in f" {lower} " or lower.startswith(f"{word} ") or lower.endswith(f" {word}"):
                self.fail(f"Report contains forbidden word '{word}': {full}")


class DefaultsConstantsTests(unittest.TestCase):
    def test_default_horizons_include_1d_5d_20d(self) -> None:
        self.assertEqual(DEFAULT_HORIZONS, (1, 5, 20))


if __name__ == "__main__":
    unittest.main()
