import unittest
from datetime import datetime, timezone

from app.services.macro_context import MacroContext
from app.services.risk_overlay import (
    calculate_risk_overlay,
    risk_overlay_notes,
)
from app.services.sector_sensitivity import get_sector_sensitivity


class RiskOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.base_risk = 35.0

    def test_risk_overlay_without_macro_context(self) -> None:
        overlay = calculate_risk_overlay(self.base_risk)
        self.assertEqual(overlay.base_risk_score, self.base_risk)
        self.assertEqual(overlay.macro_risk_adjustment, 0.0)
        self.assertEqual(overlay.adjusted_risk_score, self.base_risk)

    def test_risk_overlay_high_volatility(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=["FOMC"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction="stable",
            inflation_level="moderate",
        )
        overlay = calculate_risk_overlay(self.base_risk, macro_context=macro)
        self.assertGreater(overlay.adjusted_risk_score, self.base_risk)
        self.assertIsNotNone(overlay.risk_flag)

    def test_risk_overlay_rising_rates(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="rising",
            inflation_level="moderate",
        )
        overlay = calculate_risk_overlay(self.base_risk, macro_context=macro)
        self.assertGreater(overlay.adjusted_risk_score, self.base_risk)
        self.assertIn("rising_rates", overlay.risk_flag or "")

    def test_risk_overlay_falling_rates(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="falling",
            inflation_level="moderate",
        )
        overlay = calculate_risk_overlay(self.base_risk, macro_context=macro)
        self.assertLessEqual(overlay.adjusted_risk_score, self.base_risk)

    def test_risk_overlay_elevated_inflation(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="stable",
            inflation_level="elevated",
        )
        overlay = calculate_risk_overlay(self.base_risk, macro_context=macro)
        self.assertGreater(overlay.adjusted_risk_score, self.base_risk)

    def test_risk_overlay_tech_with_rising_rates(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="rising",
            inflation_level="moderate",
        )
        tech_sensitivity = get_sector_sensitivity("Technology")
        overlay = calculate_risk_overlay(
            self.base_risk,
            macro_context=macro,
            sector_sensitivity=tech_sensitivity,
        )
        # Tech + rising rates = significant risk increase
        self.assertGreater(
            overlay.adjusted_risk_score, self.base_risk + 10
        )
        # Should have a risk flag
        self.assertIsNotNone(overlay.risk_flag)

    def test_risk_overlay_financials_with_rising_rates(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="rising",
            inflation_level="moderate",
        )
        fin_sensitivity = get_sector_sensitivity("Financials")
        overlay = calculate_risk_overlay(
            self.base_risk,
            macro_context=macro,
            sector_sensitivity=fin_sensitivity,
        )
        # Financials benefit from rising rates so offset some of macro impact
        # Less increase than without sector adjustment
        self.assertLess(overlay.adjusted_risk_score, self.base_risk + 8.0)

    def test_risk_overlay_high_dividend_elevated_inflation(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="stable",
            inflation_level="elevated",
        )
        overlay = calculate_risk_overlay(
            self.base_risk,
            macro_context=macro,
            dividend_yield=3.5,  # High dividend
        )
        # High dividend + high inflation = risk increases
        self.assertGreater(overlay.adjusted_risk_score, self.base_risk)
        # Should have a risk flag
        self.assertIsNotNone(overlay.risk_flag)

    def test_risk_overlay_notes(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=["FOMC"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction="rising",
            inflation_level="elevated",
        )
        overlay = calculate_risk_overlay(self.base_risk, macro_context=macro)
        notes = risk_overlay_notes(overlay)
        self.assertGreater(len(notes), 0)
        # Should have some explanation
        self.assertTrue(any("risk" in note.lower() for note in notes))

    def test_risk_overlay_clamped_to_valid_range(self) -> None:
        macro = MacroContext(
            reference_date=self.now,
            upcoming_high_impact_events=["FOMC", "Jobs", "CPI"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction="rising",
            inflation_level="elevated",
        )
        overlay = calculate_risk_overlay(95.0, macro_context=macro)
        # Should not exceed 100
        self.assertLessEqual(overlay.adjusted_risk_score, 100.0)

        overlay = calculate_risk_overlay(5.0, macro_context=macro)
        # Should not be less than 0
        self.assertGreaterEqual(overlay.adjusted_risk_score, 0.0)


if __name__ == "__main__":
    unittest.main()
