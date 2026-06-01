from __future__ import annotations

import unittest
import pandas as pd

from app.services.charting import render_price_chart


class ChartingTests(unittest.TestCase):
    def _make_history(self, n: int) -> pd.DataFrame:
        index = pd.date_range("2025-01-01", periods=n, freq="B", tz="UTC")
        close = [100.0 + i * 0.5 for i in range(n)]
        return pd.DataFrame({"Close": close}, index=index)

    def test_returns_png_bytes(self) -> None:
        history = self._make_history(60)
        result = render_price_chart("AAPL", history)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result[:4] == b"\x89PNG", "Expected PNG header")

    def test_short_history_no_ma200(self) -> None:
        # Fewer than 200 rows — MA200 should be skipped without error.
        history = self._make_history(80)
        result = render_price_chart("MSFT", history)
        self.assertTrue(result[:4] == b"\x89PNG")

    def test_full_year_history(self) -> None:
        history = self._make_history(252)
        result = render_price_chart("NVDA", history)
        self.assertTrue(len(result) > 1000)


if __name__ == "__main__":
    unittest.main()
