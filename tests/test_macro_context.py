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

    def test_macro_context_summary_includes_fred_values(self) -> None:
        now = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)
        context = build_macro_context(
            now,
            fred_latest={
                "FEDFUNDS": 5.33,
                "UNRATE": 4.1,
                "CPIAUCSL": 325.0,
            },
        )

        summary = macro_context_summary(context)

        self.assertTrue(any("Fed funds 5.33%" in note for note in summary))
        self.assertTrue(any("unemployment 4.10%" in note for note in summary))
        self.assertTrue(any("CPI index 325.00" in note for note in summary))
        self.assertTrue(any("rate-sensitive" in note for note in summary))

    def test_macro_context_summary_marks_partial_fred_values(self) -> None:
        now = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)
        context = build_macro_context(now, fred_latest={"FEDFUNDS": 4.33})

        summary = macro_context_summary(context)

        self.assertTrue(any("Fed funds 4.33%" in note for note in summary))
        self.assertTrue(any("missing unemployment, CPI" in note for note in summary))

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


    def test_rate_direction_rising_from_history(self) -> None:
        now = datetime.now(timezone.utc)
        context = build_macro_context(
            now,
            fred_latest={"FEDFUNDS": 5.33},
            fred_history={"FEDFUNDS": [4.33, 4.83, 5.10, 5.33]},
        )
        self.assertEqual(context.rate_direction, "rising")

    def test_rate_direction_falling_from_history(self) -> None:
        now = datetime.now(timezone.utc)
        context = build_macro_context(
            now,
            fred_latest={"FEDFUNDS": 4.33},
            fred_history={"FEDFUNDS": [5.33, 5.10, 4.83, 4.33]},
        )
        self.assertEqual(context.rate_direction, "falling")
        summary = macro_context_summary(context)
        self.assertTrue(any("ставка снижается" in note for note in summary))

    def test_rate_direction_stable_within_noise(self) -> None:
        now = datetime.now(timezone.utc)
        context = build_macro_context(
            now,
            fred_latest={"FEDFUNDS": 5.33},
            fred_history={"FEDFUNDS": [5.31, 5.32, 5.33]},
        )
        self.assertEqual(context.rate_direction, "stable")

    def test_rate_direction_falls_back_to_stable_without_history(self) -> None:
        now = datetime.now(timezone.utc)
        context = build_macro_context(now, fred_latest={"FEDFUNDS": 5.33})
        self.assertEqual(context.rate_direction, "stable")

    def test_inflation_level_from_yoy_history_elevated(self) -> None:
        now = datetime.now(timezone.utc)
        # 13 monthly points; current is ~3.5% above the year-ago value, so the
        # YoY trend (not the absolute CPI index) drives the elevated reading.
        year_ago = 300.0
        current = year_ago * 1.035
        history = [year_ago + i * (current - year_ago) / 12 for i in range(13)]
        context = build_macro_context(
            now,
            fred_latest={"CPIAUCSL": current},
            fred_history={"CPIAUCSL": history},
        )
        self.assertEqual(context.inflation_level, "elevated")

    def test_inflation_level_from_yoy_history_low(self) -> None:
        now = datetime.now(timezone.utc)
        # High absolute CPI index but only ~1% YoY -> low, proving trend wins.
        year_ago = 320.0
        current = year_ago * 1.01
        history = [year_ago + i * (current - year_ago) / 12 for i in range(13)]
        context = build_macro_context(
            now,
            fred_latest={"CPIAUCSL": current},
            fred_history={"CPIAUCSL": history},
        )
        self.assertEqual(context.inflation_level, "low")

    def test_inflation_level_falls_back_to_absolute_without_history(self) -> None:
        now = datetime.now(timezone.utc)
        context = build_macro_context(
            now,
            fred_latest={"CPIAUCSL": 325.0},
            fred_history={"CPIAUCSL": [324.0, 325.0]},  # too few points for YoY
        )
        self.assertEqual(context.inflation_level, "elevated")


if __name__ == "__main__":
    unittest.main()
