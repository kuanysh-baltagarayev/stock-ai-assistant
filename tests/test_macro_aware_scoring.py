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
            trailing_pe=20.0,
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

    def test_rising_rate_macro_risk_hits_technology_more_than_financials(self) -> None:
        reference_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        macro = MacroContext(
            reference_date=reference_time,
            upcoming_high_impact_events=["FOMC", "CPI"],
            recent_macro_data={},
            volatility_level="high",
            rate_direction="rising",
            inflation_level="elevated",
        )
        tech = score_stock(
            self.price,
            self.technicals,
            Fundamentals(company_name="Tech Co", sector="Technology"),
            macro_context=macro,
            reference_time=reference_time,
        )
        financials = score_stock(
            self.price,
            self.technicals,
            Fundamentals(company_name="Bank Co", sector="Financials"),
            macro_context=macro,
            reference_time=reference_time,
        )

        self.assertGreater(tech.scores.risk_score, financials.scores.risk_score)
        self.assertLess(tech.scores.final_score, financials.scores.final_score)
        self.assertTrue(any("Technology is rate-sensitive" in reason for reason in tech.reasons))

    def test_earnings_risk_hits_growth_sensitive_sector_more_than_defensive_sector(self) -> None:
        reference_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        event_calendar = {
            "upcoming_events": [
                {
                    "name": "earnings",
                    "scheduled_at": "2026-06-03T20:00:00+00:00",
                }
            ]
        }
        tech = score_stock(
            self.price,
            self.technicals,
            Fundamentals(company_name="Tech Co", sector="Technology"),
            macro_context=None,
            event_calendar=event_calendar,
            reference_time=reference_time,
        )
        utilities = score_stock(
            self.price,
            self.technicals,
            Fundamentals(company_name="Utility Co", sector="Utilities"),
            macro_context=None,
            event_calendar=event_calendar,
            reference_time=reference_time,
        )

        self.assertGreater(tech.scores.risk_score, utilities.scores.risk_score)
        self.assertLess(tech.scores.final_score, utilities.scores.final_score)
        self.assertTrue(any("earnings reactions tend to be sharper" in reason for reason in tech.reasons))


class PoliticalRegulatoryRiskTests(unittest.TestCase):
    def _make_macro(self, political_risk_level: str | None, sector: str = "Technology") -> MacroContext:
        return MacroContext(
            reference_date=datetime.now(timezone.utc),
            upcoming_high_impact_events=[],
            recent_macro_data={},
            volatility_level="low",
            rate_direction="stable",
            inflation_level="moderate",
            political_risk_level=political_risk_level,
        )

    def _base_inputs(self, sector: str = "Technology"):
        technicals = TechnicalIndicators(
            moving_average_50=145.0,
            moving_average_200=140.0,
            change_1d_pct=0.5,
            change_1m_pct=2.0,
            rsi=50.0,
        )
        fundamentals = Fundamentals(
            company_name="Test Inc.",
            sector=sector,
            trailing_pe=20.0,
        )
        return technicals, fundamentals

    def test_no_political_risk_baseline(self) -> None:
        technicals, fundamentals = self._base_inputs()
        macro = self._make_macro(None)
        result = score_stock(150.0, technicals, fundamentals, macro_context=macro)
        self.assertNotIn("political", " ".join(result.reasons).lower())

    def test_elevated_political_risk_raises_risk_score(self) -> None:
        technicals, fundamentals = self._base_inputs()
        macro_no_risk = self._make_macro(None)
        macro_elevated = self._make_macro("elevated")
        result_baseline = score_stock(150.0, technicals, fundamentals, macro_context=macro_no_risk)
        result_elevated = score_stock(150.0, technicals, fundamentals, macro_context=macro_elevated)
        self.assertGreater(result_elevated.scores.risk_score, result_baseline.scores.risk_score)

    def test_high_political_risk_raises_risk_score_more_than_elevated(self) -> None:
        technicals, fundamentals = self._base_inputs()
        macro_elevated = self._make_macro("elevated")
        macro_high = self._make_macro("high")
        result_elevated = score_stock(150.0, technicals, fundamentals, macro_context=macro_elevated)
        result_high = score_stock(150.0, technicals, fundamentals, macro_context=macro_high)
        self.assertGreater(result_high.scores.risk_score, result_elevated.scores.risk_score)

    def test_tech_sector_amplified_by_regulatory_risk(self) -> None:
        """Technology sector gets amplified risk due to antitrust/export keyword match."""
        tech_technicals, tech_fundamentals = self._base_inputs("Technology")
        utilities_technicals, utilities_fundamentals = self._base_inputs("Utilities")
        macro = self._make_macro("elevated")
        tech_result = score_stock(150.0, tech_technicals, tech_fundamentals, macro_context=macro)
        utilities_result = score_stock(150.0, utilities_technicals, utilities_fundamentals, macro_context=macro)
        self.assertGreater(tech_result.scores.risk_score, utilities_result.scores.risk_score)

    def test_industrials_sector_amplified_by_tariff_risk(self) -> None:
        """Industrials sector gets amplified risk (tariff/trade war exposure)."""
        ind_technicals, ind_fundamentals = self._base_inputs("Industrials")
        staples_technicals, staples_fundamentals = self._base_inputs("Consumer Staples")
        macro = self._make_macro("elevated")
        ind_result = score_stock(150.0, ind_technicals, ind_fundamentals, macro_context=macro)
        staples_result = score_stock(150.0, staples_technicals, staples_fundamentals, macro_context=macro)
        self.assertGreater(ind_result.scores.risk_score, staples_result.scores.risk_score)

    def test_political_risk_reason_in_output(self) -> None:
        technicals, fundamentals = self._base_inputs()
        macro = self._make_macro("high")
        result = score_stock(150.0, technicals, fundamentals, macro_context=macro)
        self.assertTrue(any("political" in r.lower() or "regulatory" in r.lower() for r in result.reasons))


class PoliticalRiskFromNewsTests(unittest.TestCase):
    def _make_news_item(self, title: str, score: float = -0.5, source: str = "Reuters") -> object:
        from app.services.news_collector import NewsItem
        return NewsItem(
            title=title, url=None, source=source, published_at=None, summary=None,
            sentiment_score=score, sentiment_label="negative",
            relevance=None, category="macro",
        )

    def test_no_political_news_returns_none(self) -> None:
        from app.services.news_collector import NewsContext, political_risk_level_from_news
        ctx = NewsContext(items=[self._make_news_item("Markets rally on earnings")])
        self.assertIsNone(political_risk_level_from_news(ctx))

    def test_one_tariff_headline_returns_elevated(self) -> None:
        from app.services.news_collector import NewsContext, political_risk_level_from_news
        ctx = NewsContext(items=[self._make_news_item("New tariffs on Chinese goods announced")])
        self.assertEqual(political_risk_level_from_news(ctx), "elevated")

    def test_two_political_headlines_return_high(self) -> None:
        from app.services.news_collector import NewsContext, political_risk_level_from_news
        ctx = NewsContext(items=[
            self._make_news_item("New tariffs on Chinese goods announced"),
            self._make_news_item("FTC opens antitrust probe into Big Tech"),
        ])
        self.assertEqual(political_risk_level_from_news(ctx), "high")

    def test_low_weight_source_ignored(self) -> None:
        from app.services.news_collector import NewsContext, political_risk_level_from_news
        ctx = NewsContext(items=[self._make_news_item("Tariff news", source=None)])
        self.assertIsNone(political_risk_level_from_news(ctx))

    def test_build_macro_context_with_news_sets_political_risk(self) -> None:
        from app.services.news_collector import NewsContext
        from app.services.macro_context import build_macro_context
        news_item = self._make_news_item("New tariffs imposed on EU steel imports")
        ctx = NewsContext(items=[news_item])
        macro = build_macro_context(datetime.now(timezone.utc), news_context=ctx)
        self.assertEqual(macro.political_risk_level, "elevated")

    def test_build_macro_context_without_news_has_no_political_risk(self) -> None:
        from app.services.macro_context import build_macro_context
        macro = build_macro_context(datetime.now(timezone.utc), news_context=None)
        self.assertIsNone(macro.political_risk_level)


class MarketRegimeAwareScoringTests(unittest.TestCase):
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
            trailing_pe=20.0,
            debt_to_equity=0.5,
        )

    def _regime(self, **overrides):
        from app.services.market_regime import MarketRegime

        defaults = dict(
            reference_date=datetime.now(timezone.utc),
            index_trend="uptrend",
            volatility_regime="low",
            rates_backdrop="stable",
            sector_rotation="risk_on",
            risk_appetite="risk_on",
            confidence=1.0,
            source_provenance={"provider_name": "yfinance"},
        )
        defaults.update(overrides)
        return MarketRegime(**defaults)

    def test_risk_off_regime_raises_risk_score(self) -> None:
        baseline = score_stock(self.price, self.technicals, self.fundamentals)
        risk_off = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            market_regime=self._regime(
                index_trend="downtrend",
                volatility_regime="high",
                sector_rotation="risk_off",
                risk_appetite="risk_off",
            ),
        )
        self.assertGreater(risk_off.scores.risk_score, baseline.scores.risk_score)
        self.assertLess(risk_off.scores.final_score, baseline.scores.final_score)
        self.assertTrue(
            any("risk-off market regime" in r for r in risk_off.reasons)
        )

    def test_risk_on_regime_lowers_risk_score(self) -> None:
        baseline = score_stock(self.price, self.technicals, self.fundamentals)
        risk_on = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            market_regime=self._regime(),
        )
        self.assertLess(risk_on.scores.risk_score, baseline.scores.risk_score)

    def test_regime_risk_adjustment_is_capped(self) -> None:
        baseline = score_stock(self.price, self.technicals, self.fundamentals)
        extreme = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            market_regime=self._regime(
                index_trend="downtrend",
                volatility_regime="high",
                sector_rotation="risk_off",
                risk_appetite="risk_off",
                confidence=1.0,
            ),
        )
        # Risk-off + high vol at full confidence must stay within the 5-point cap.
        delta = extreme.scores.risk_score - baseline.scores.risk_score
        self.assertLessEqual(delta, 5.0 + 1e-6)
        self.assertGreater(delta, 0.0)

    def test_low_confidence_regime_has_smaller_effect(self) -> None:
        baseline = score_stock(self.price, self.technicals, self.fundamentals)
        weak = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            market_regime=self._regime(
                risk_appetite="risk_off", volatility_regime="elevated", confidence=0.2
            ),
        )
        strong = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            market_regime=self._regime(
                risk_appetite="risk_off", volatility_regime="elevated", confidence=1.0
            ),
        )
        weak_delta = weak.scores.risk_score - baseline.scores.risk_score
        strong_delta = strong.scores.risk_score - baseline.scores.risk_score
        self.assertLess(weak_delta, strong_delta)

    def test_unknown_regime_is_a_noop(self) -> None:
        baseline = score_stock(self.price, self.technicals, self.fundamentals)
        unknown = score_stock(
            self.price,
            self.technicals,
            self.fundamentals,
            market_regime=self._regime(
                index_trend="unknown",
                volatility_regime="unknown",
                rates_backdrop="unknown",
                sector_rotation="unknown",
                risk_appetite="unknown",
                confidence=0.0,
            ),
        )
        self.assertEqual(unknown.scores.risk_score, baseline.scores.risk_score)
        self.assertEqual(unknown.scores.final_score, baseline.scores.final_score)

    def test_regime_affects_weights_within_bounds(self) -> None:
        from app.services.scoring import _adaptive_weights

        base_w = _adaptive_weights(None)
        regime_w = _adaptive_weights(
            None,
            market_regime=self._regime(
                volatility_regime="high",
                risk_appetite="risk_off",
            ),
        )
        self.assertAlmostEqual(sum(regime_w), 1.0, places=3)
        # Risk weight should rise but only modestly (bounded nudge).
        self.assertGreater(regime_w[2], base_w[2])
        self.assertLess(regime_w[2] - base_w[2], 0.05)


if __name__ == "__main__":
    unittest.main()
