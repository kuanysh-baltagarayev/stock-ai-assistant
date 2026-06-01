import unittest
from datetime import datetime, timezone

from app.schemas import Fundamentals, TechnicalIndicators
from app.services.macro_context import MacroContext
from app.services.scoring import score_stock


class MacroAwareScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.price = 150.0
        self.technicals = TechnicalIndicators(
            moving_average_50=145.0,
            moving_average_200=140.0,
            change_1d_pct=1.5,
            change_1m_pct=5.0,
            change_6m_pct=20.0,
            rsi=55.0,
            max_drawdown=10.0,
        )
        self.fundamentals = Fundamentals(
            company_name="Test Inc.",
            sector="Technology",
            pe_ratio=20.0,
            dividend_yield=1.5,
            debt_to_equity=0.5,
        )

    def test_score_without_macro_context(self) -> None:
        result = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
        )
        self.assertIsNotNone(result.scores.final_score)
        self.assertIsNotNone(result.recommendation)

    def test_score_with_normal_macro_context(self) -> None:
        macro = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="stable",
            inflation_level="moderate",
        )
        result = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=macro,
        )
        self.assertIsNotNone(result.scores.final_score)
        self.assertGreater(result.scores.final_score, 0)

    def test_score_with_high_volatility_context(self) -> None:
        macro = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=["FOMC Meeting"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction="rising",
            inflation_level="elevated",
        )
        result = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=macro,
        )
        # In high-volatility, momentum becomes more important,
        # so a strong momentum signal (price above MAs) should contribute more
        self.assertIsNotNone(result.scores.final_score)
        self.assertGreater(result.scores.final_score, 50)

    def test_macro_context_does_not_break_recommendation(self) -> None:
        macro = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="high",
            rate_direction="rising",
            inflation_level="elevated",
        )
        result = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=macro,
        )
        # Should still have a valid recommendation
        valid_recommendations = {
            "BUY", "HOLD", "SELL", "STRONG BUY", "STRONG SELL", "WATCH", "NEUTRAL"
        }
        self.assertIn(result.recommendation, valid_recommendations)

    def test_different_macro_conditions_affect_score(self) -> None:
        # Low volatility, stable conditions
        macro_low_vol = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="stable",
            inflation_level="moderate",
        )
        result_low = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=macro_low_vol,
        )

        # High volatility, rising rates, elevated inflation
        macro_high_vol = MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=["FOMC", "CPI"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction="rising",
            inflation_level="elevated",
        )
        result_high = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=macro_high_vol,
        )

        # Scores should be different due to different weights
        # (though not guaranteed to be strictly ordered)
        self.assertNotEqual(result_low.scores.final_score, result_high.scores.final_score)


if __name__ == "__main__":
    unittest.main()
