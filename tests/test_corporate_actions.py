"""Tests for corporate-action detection in market_data data-quality flags."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import pandas as pd

from app.services.market_data import _build_data_quality


def _make_history(close_values: list[float], start: str = "2025-01-02") -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame for testing data-quality detection."""
    dates = pd.bdate_range(start=start, periods=len(close_values))
    close = pd.Series(close_values, index=dates, name="Close", dtype=float)
    open_px = close * 0.99
    high_px = close * 1.02
    low_px = close * 0.98
    volume = pd.Series([1_000_000] * len(close_values), index=dates, name="Volume", dtype=float)
    frame = pd.DataFrame({"Open": open_px, "High": high_px, "Low": low_px, "Close": close, "Volume": volume})
    return frame


class BuildDataQualityCorporateActionsTest(unittest.TestCase):
    """Test that _build_data_quality detects splits, dividends, missing candles."""

    def _dq(self, **overrides: object) -> dict:
        defaults = {
            "info": {"longName": "Test"},
            "price": 150.0,
            "price_source": "info.currentPrice",
            "close_price": 150.0,
            "fast_price": 150.0,
            "current_price": 150.0,
            "regular_market_price": 150.0,
            "latest_history_timestamp": datetime.now(timezone.utc),
            "fetched_at": datetime.now(timezone.utc),
            "currency": "USD",
            "history": None,
        }
        defaults.update(overrides)
        return _build_data_quality(**defaults)

    def test_normal_data_no_flags(self):
        """Normal daily data should not raise CA flags."""
        history = _make_history([100.0 + i for i in range(100)])
        dq = self._dq(history=history)
        self.assertFalse(dq["split_detected"])
        self.assertFalse(dq["dividend_detected"])
        self.assertEqual(dq["missing_candles"], 0)
        self.assertFalse(dq["partial_session"])
        self.assertIsNone(dq["adjustment_policy_warning"])
        self.assertGreaterEqual(dq["confidence"], 0.95)

    def test_split_detected_in_raw_data(self):
        """A >33% daily jump in raw-close data should flag a split."""
        # Day 1-50: normal; day 51: 4x jump simulates a stock split
        values = [100.0 + i * 0.5 for i in range(50)]
        values.append(values[-1] * 4.0)  # reverse-split-like jump
        values.extend(values[-1] + i * 0.5 for i in range(10))
        history = _make_history(values)
        dq = self._dq(history=history)
        self.assertTrue(dq["split_detected"])
        self.assertIsNotNone(dq["adjustment_policy_warning"])

    def test_reverse_split_detected(self):
        """A >33% daily drop in raw-close data should flag a split."""
        values = [100.0 + i * 0.5 for i in range(30)]
        values.append(values[-1] * 0.25)  # reverse-split drop
        values.extend(values[-1] + i * 0.3 for i in range(5))
        history = _make_history(values)
        dq = self._dq(history=history)
        self.assertTrue(dq["split_detected"])

    def test_dividend_detected(self):
        """A 2% price drop (common ex-dividend) should flag dividend."""
        values = [100.0 + i for i in range(40)]
        # Simulate ex-dividend: 2.5% drop
        values.append(values[-1] * 0.975)
        values.extend(values[-1] + i * 0.5 for i in range(5))
        history = _make_history(values)
        dq = self._dq(history=history)
        self.assertTrue(dq["dividend_detected"])

    def test_missing_candles_detected(self):
        """Gaps >4 calendar days should be counted as missing candles."""
        # Use weekly data so only 1 day per week → big gaps
        dates = pd.date_range("2025-01-01", periods=10, freq="7D")
        close = pd.Series([100.0 + i for i in range(10)], index=dates, name="Close", dtype=float)
        volume = pd.Series([1_000_000] * 10, index=dates, name="Volume", dtype=float)
        history = pd.DataFrame({"Close": close, "Volume": volume})
        dq = self._dq(history=history)
        self.assertGreater(dq["missing_candles"], 0)

    def test_no_missing_candles_in_business_days(self):
        """Consecutive business days should not flag missing candles."""
        history = _make_history([100.0 + i for i in range(50)])
        dq = self._dq(history=history)
        self.assertEqual(dq["missing_candles"], 0)

    def test_no_history_no_ca_flags(self):
        """Without a history DataFrame, no CA flags are raised."""
        dq = self._dq(history=None)
        self.assertFalse(dq["split_detected"])
        self.assertFalse(dq["dividend_detected"])
        self.assertEqual(dq["missing_candles"], 0)
        self.assertFalse(dq["partial_session"])

    def test_empty_history_no_ca_flags(self):
        """An empty history DataFrame should not raise CA flags."""
        dq = self._dq(history=pd.DataFrame())
        self.assertFalse(dq["split_detected"])
        self.assertFalse(dq["dividend_detected"])
        self.assertEqual(dq["missing_candles"], 0)
        self.assertFalse(dq["partial_session"])

    def test_confidence_reduced_by_split(self):
        """Split detection should reduce confidence."""
        values = [100.0 + i * 0.5 for i in range(50)]
        values.append(values[-1] * 4.0)
        values.extend(values[-1] + i * 0.5 for i in range(5))
        history = _make_history(values)
        dq = self._dq(history=history)
        self.assertLess(dq["confidence"], 0.9)

    def test_confidence_reduced_by_missing_candles(self):
        """Missing candles should reduce confidence."""
        dates = pd.date_range("2025-01-01", periods=10, freq="14D")
        close = pd.Series([100.0 + i for i in range(10)], index=dates, name="Close", dtype=float)
        volume = pd.Series([1_000_000] * 10, index=dates, name="Volume", dtype=float)
        history = pd.DataFrame({"Close": close, "Volume": volume})
        dq = self._dq(history=history)
        self.assertLess(dq["confidence"], 0.95)
        self.assertGreater(dq["missing_candles"], 0)

    def test_summary_includes_corporate_actions(self):
        """Summary string should mention detected CA events."""
        values = [100.0 + i * 0.5 for i in range(50)]
        values.append(values[-1] * 4.0)  # split
        values.append(values[-1] * 0.975)  # dividend
        history = _make_history(values)
        dq = self._dq(history=history)
        summary = dq.get("summary", "")
        self.assertIn("split", summary.lower())

    def test_all_new_fields_present(self):
        """Verify the dict shape has all new CA fields."""
        dq = self._dq()
        self.assertIn("split_detected", dq)
        self.assertIn("dividend_detected", dq)
        self.assertIn("missing_candles", dq)
        self.assertIn("partial_session", dq)
        self.assertIn("adjustment_policy_warning", dq)
