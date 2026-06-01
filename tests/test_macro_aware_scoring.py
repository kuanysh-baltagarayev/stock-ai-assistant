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

    def test_recent_8k_increases_risk_score(self) -> None:
        reference_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        result_without_filing = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
            reference_time=reference_time,
        )
        result_with_filing = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
            sec_filings={
                "recent_filings": [
                    {
                        "form_type": "8-K",
                        "filing_date": "2026-05-30",
                        "description": "Current report",
                    }
                ]
            },
            reference_time=reference_time,
        )

        self.assertGreater(
            result_with_filing.scores.risk_score,
            result_without_filing.scores.risk_score,
        )
        self.assertLess(
            result_with_filing.scores.final_score,
            result_without_filing.scores.final_score,
        )
        self.assertTrue(any("8-K" in reason for reason in result_with_filing.reasons))

    def test_stale_filing_does_not_change_risk_score(self) -> None:
        reference_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        baseline = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
            reference_time=reference_time,
        )
        stale = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
            sec_filings={
                "recent_filings": [
                    {
                        "form_type": "10-Q",
                        "filing_date": "2025-01-15",
                        "description": "Old quarterly report",
                    }
                ]
            },
            reference_time=reference_time,
        )

        self.assertEqual(stale.scores.risk_score, baseline.scores.risk_score)
        self.assertEqual(stale.scores.final_score, baseline.scores.final_score)

    def test_catalyst_cluster_increases_risk_more_than_routine_filing(self) -> None:
        reference_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        filing_only = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
            sec_filings={
                "recent_filings": [
                    {
                        "form_type": "8-K",
                        "filing_date": "2026-05-30",
                        "description": "Current report",
                    }
                ]
            },
            reference_time=reference_time,
        )
        clustered = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=MacroContext(
                reference_date=reference_time,
                upcoming_high_impact_events=["FOMC", "CPI"],
                recent_macro_data={},
                volatility_level="high",
                rate_direction="stable",
                inflation_level="moderate",
            ),
            event_calendar={
                "upcoming_events": [
                    {
                        "name": "earnings",
                        "scheduled_at": "2026-06-03T20:00:00+00:00",
                    }
                ]
            },
            sec_filings={
                "recent_filings": [
                    {
                        "form_type": "8-K",
                        "filing_date": "2026-05-30",
                        "description": "Current report",
                    }
                ]
            },
            reference_time=reference_time,
        )

        self.assertGreater(clustered.scores.risk_score, filing_only.scores.risk_score)
        self.assertLess(clustered.scores.final_score, filing_only.scores.final_score)
        self.assertTrue(
            any("multiple near-term catalysts" in reason for reason in clustered.reasons)
        )

    def test_distant_earnings_do_not_add_event_risk(self) -> None:
        reference_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        baseline = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
            reference_time=reference_time,
        )
        distant_earnings = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            macro_context=None,
            event_calendar={
                "upcoming_events": [
                    {
                        "name": "earnings",
                        "scheduled_at": "2026-07-01T20:00:00+00:00",
                    }
                ]
            },
            reference_time=reference_time,
        )

        self.assertEqual(distant_earnings.scores.risk_score, baseline.scores.risk_score)
        self.assertEqual(distant_earnings.scores.final_score, baseline.scores.final_score)


if __name__ == "__main__":
    unittest.main()
