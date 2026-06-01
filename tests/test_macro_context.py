import unittest
from datetime import datetime, timezone

from app.services.macro_context import (
    MacroContext,
    alert_weight_adjustment,
    build_macro_context,
    macro_context_summary,
)


class MacroContextTests(unittest.TestCase):
    def test_build_macro_context_without_fred_data(self) -> None:
        now = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)
        context = build_macro_context(now)
        self.assertIsNotNone(context)
        self.assertEqual(context.reference_date, now)
        self.assertIsNone(context.rate_direction)

    def test_build_macro_context_with_fred_data(self) -> None:
        now = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)
        fred_data = {
            "FEDFUNDS": 4.33,
            "UNRATE": 4.1,
            "CPIAUCSL": 314.2,
        }
        context = build_macro_context(now, fred_latest=fred_data)
        self.assertEqual(context.recent_macro_data["fed_rate"], 4.33)
        self.assertEqual(context.recent_macro_data["unemployment"], 4.1)
        self.assertEqual(context.recent_macro_data["cpi"], 314.2)

    def test_macro_context_summary_with_events(self) -> None:
        now = datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc)
        context = build_macro_context(now)
        # Jan 10 has jobs report and Jan 15 has CPI
        summary = macro_context_summary(context)
        self.assertGreater(len(summary), 0)
        # Should mention upcoming events
        self.assertTrue(any("события" in note for note in summary))

    def test_macro_context_summary_high_volatility(self) -> None:
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        context = MacroContext(
            reference_date=now,
            upcoming_high_impact_events=["FOMC Meeting", "Jobs Report"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction=None,
            inflation_level=None,
        )
        summary = macro_context_summary(context)
        # Should mention high volatility
        self.assertTrue(any("волатил" in note for note in summary))

    def test_alert_weight_adjustment_normal(self) -> None:
        context = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction=None,
            inflation_level="moderate",
        )
        weight = alert_weight_adjustment(context)
        self.assertAlmostEqual(weight, 0.8, places=1)

    def test_alert_weight_adjustment_high_volatility(self) -> None:
        context = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=["FOMC Meeting"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction=None,
            inflation_level=None,
        )
        weight = alert_weight_adjustment(context)
        self.assertGreaterEqual(weight, 1.3)

    def test_alert_weight_adjustment_elevated_inflation(self) -> None:
        context = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="rising",
            inflation_level="elevated",
        )
        weight = alert_weight_adjustment(context)
        self.assertGreaterEqual(weight, 1.0)

    def test_inflation_level_inference(self) -> None:
        # High CPI (elevated inflation)
        now = datetime.now(timezone.utc)
        fred_data = {"CPIAUCSL": 325.0}
        context = build_macro_context(now, fred_latest=fred_data)
        self.assertEqual(context.inflation_level, "elevated")

        # Moderate CPI
        fred_data = {"CPIAUCSL": 315.0}
        context = build_macro_context(now, fred_latest=fred_data)
        self.assertEqual(context.inflation_level, "moderate")

        # Low CPI
        fred_data = {"CPIAUCSL": 305.0}
        context = build_macro_context(now, fred_latest=fred_data)
        self.assertEqual(context.inflation_level, "low")

    def test_volatility_inference_from_unemployment(self) -> None:
        now = datetime.now(timezone.utc)
        # Low unemployment = volatility
        fred_data = {"UNRATE": 3.2}
        context = build_macro_context(now, fred_latest=fred_data)
        self.assertEqual(context.volatility_level, "medium")

        # High unemployment = volatility
        fred_data = {"UNRATE": 7.0}
        context = build_macro_context(now, fred_latest=fred_data)
        self.assertEqual(context.volatility_level, "medium")

        # Normal unemployment
        fred_data = {"UNRATE": 4.5}
        context = build_macro_context(now, fred_latest=fred_data)
        self.assertEqual(context.volatility_level, "low")


if __name__ == "__main__":
    unittest.main()
