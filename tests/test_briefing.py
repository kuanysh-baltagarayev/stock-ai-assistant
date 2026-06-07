from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.services.briefing import build_scan_briefing


class ScanBriefingTests(unittest.TestCase):
    def test_build_scan_briefing_groups_key_watch_and_risk_items(self) -> None:
        summary = build_scan_briefing(
            [
                SimpleNamespace(
                    ticker="AAPL",
                    recommendation="HIGH_INTEREST",
                    final_score=84.0,
                    price=189.12,
                    short_reason="strong setup",
                    confidence=0.91,
                    risk_score=38.0,
                ),
                SimpleNamespace(
                    ticker="MSFT",
                    recommendation="NEUTRAL",
                    final_score=61.0,
                    price=402.0,
                    short_reason="balanced setup",
                    confidence=0.82,
                    risk_score=45.0,
                ),
                SimpleNamespace(
                    ticker="NVDA",
                    recommendation="CAUTION",
                    final_score=41.0,
                    price=120.0,
                    short_reason="event risk",
                    confidence=0.77,
                    risk_score=74.0,
                ),
            ],
            [],
        )

        self.assertEqual([item.ticker for item in summary.key_items], ["AAPL"])
        self.assertEqual([item.ticker for item in summary.watch_items], ["MSFT"])
        self.assertEqual([item.ticker for item in summary.risk_items], ["NVDA"])
        self.assertEqual(summary.degraded_count, 1)
        self.assertIn("high risk 74", summary.risk_items[0].flags)

    def test_build_scan_briefing_filters_low_confidence_results(self) -> None:
        summary = build_scan_briefing(
            [
                SimpleNamespace(
                    ticker="AAPL",
                    recommendation="WATCH",
                    final_score=72.0,
                    price=189.12,
                    short_reason="ok",
                    confidence=0.81,
                    risk_score=40.0,
                ),
                SimpleNamespace(
                    ticker="TSLA",
                    recommendation="WATCH",
                    final_score=70.0,
                    price=260.0,
                    short_reason="low confidence",
                    confidence=0.42,
                    risk_score=52.0,
                ),
                SimpleNamespace(
                    ticker="META",
                    recommendation="WATCH",
                    final_score=68.0,
                    price=510.0,
                    short_reason="missing confidence",
                    risk_score=50.0,
                ),
            ],
            [],
            min_confidence=0.8,
        )

        self.assertEqual([item.ticker for item in summary.items], ["AAPL"])
        self.assertEqual(summary.hidden_low_confidence_count, 2)

    def test_build_scan_briefing_surfaces_data_quality_flags(self) -> None:
        summary = build_scan_briefing(
            [
                SimpleNamespace(
                    ticker="AMD",
                    recommendation="NEUTRAL",
                    final_score=55.0,
                    price=160.0,
                    short_reason="mixed",
                    data_quality={
                        "confidence": 0.58,
                        "stale": True,
                        "source_disagreed": True,
                    },
                    risk_score=55.0,
                ),
            ],
            [SimpleNamespace(ticker="NVDA", error="timeout")],
        )

        item = summary.items[0]
        self.assertEqual(summary.error_count, 1)
        self.assertIn("low confidence 0.58", item.flags)
        self.assertIn("stale data", item.flags)
        self.assertIn("source disagreement", item.flags)
