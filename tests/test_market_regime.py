import unittest
from datetime import datetime, timezone

from app.services.market_regime import (
    MarketRegime,
    build_market_regime,
    collect_market_regime,
    market_regime_summary,
)


def _trend_series(start: float, step: float, n: int = 80) -> list[float]:
    """Oldest-first close series with a constant per-day drift."""
    return [start + step * i for i in range(n)]


class BuildMarketRegimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ref = datetime(2026, 6, 8, tzinfo=timezone.utc)

    def test_risk_on_from_offline_fixtures(self) -> None:
        regime = build_market_regime(
            self.ref,
            index_closes={
                "SPY": _trend_series(400.0, 1.0),
                "QQQ": _trend_series(350.0, 1.0),
            },
            vix_values=[14.0, 13.5, 13.0],
            yield_values=[42.0, 42.0, 42.0],
            sector_returns={"XLK": 0.06, "XLY": 0.05, "XLP": 0.01, "XLU": 0.0},
        )
        self.assertEqual(regime.index_trend, "uptrend")
        self.assertEqual(regime.volatility_regime, "low")
        self.assertEqual(regime.sector_rotation, "risk_on")
        self.assertEqual(regime.risk_appetite, "risk_on")
        self.assertGreater(regime.confidence, 0.9)
        self.assertTrue(regime.is_known)

    def test_risk_off_from_offline_fixtures(self) -> None:
        regime = build_market_regime(
            self.ref,
            index_closes={
                "SPY": _trend_series(500.0, -1.5),
                "QQQ": _trend_series(450.0, -1.5),
            },
            vix_values=[28.0, 32.0, 34.0],
            yield_values=[42.0, 43.0, 44.0],
            sector_returns={"XLK": -0.06, "XLY": -0.05, "XLP": 0.01, "XLU": 0.02},
        )
        self.assertEqual(regime.index_trend, "downtrend")
        self.assertEqual(regime.volatility_regime, "high")
        self.assertEqual(regime.rates_backdrop, "rising")
        self.assertEqual(regime.sector_rotation, "risk_off")
        self.assertEqual(regime.risk_appetite, "risk_off")
        self.assertTrue(regime.is_known)

    def test_sideways_when_index_flat(self) -> None:
        regime = build_market_regime(
            self.ref,
            index_closes={
                "SPY": _trend_series(400.0, 0.0),
                "QQQ": _trend_series(350.0, 0.0),
            },
            vix_values=[18.0],
            yield_values=[42.0, 42.0],
            sector_returns={"XLK": 0.0, "XLP": 0.0},
        )
        self.assertEqual(regime.index_trend, "sideways")
        self.assertEqual(regime.volatility_regime, "normal")

    def test_missing_vix_and_yield_degrades_confidence(self) -> None:
        full = build_market_regime(
            self.ref,
            index_closes={
                "SPY": _trend_series(400.0, 1.0),
                "QQQ": _trend_series(350.0, 1.0),
            },
            vix_values=[14.0],
            yield_values=[42.0, 42.5],
            sector_returns={"XLK": 0.06, "XLP": 0.0},
        )
        degraded = build_market_regime(
            self.ref,
            index_closes={
                "SPY": _trend_series(400.0, 1.0),
                "QQQ": _trend_series(350.0, 1.0),
            },
            vix_values=None,
            yield_values=None,
            sector_returns={"XLK": 0.06, "XLP": 0.0},
        )
        # Missing inputs lower confidence but do not raise or go unknown.
        self.assertLess(degraded.confidence, full.confidence)
        self.assertEqual(degraded.volatility_regime, "unknown")
        self.assertEqual(degraded.rates_backdrop, "unknown")
        self.assertTrue(degraded.is_known)

    def test_empty_inputs_yield_unknown_zero_confidence(self) -> None:
        regime = build_market_regime(self.ref)
        self.assertEqual(regime.risk_appetite, "unknown")
        self.assertEqual(regime.confidence, 0.0)
        self.assertFalse(regime.is_known)

    def test_partial_index_set_reduces_confidence(self) -> None:
        regime = build_market_regime(
            self.ref,
            index_closes={"SPY": _trend_series(400.0, 1.0)},
            vix_values=[14.0],
            yield_values=[42.0, 42.0],
            sector_returns={"XLK": 0.06, "XLP": 0.0},
        )
        self.assertEqual(regime.index_trend, "uptrend")
        self.assertLess(regime.confidence, 1.0)


class MarketRegimeSummaryTests(unittest.TestCase):
    def test_summary_includes_appetite_and_confidence(self) -> None:
        regime = MarketRegime(
            reference_date=datetime(2026, 6, 8, tzinfo=timezone.utc),
            index_trend="uptrend",
            volatility_regime="low",
            rates_backdrop="stable",
            sector_rotation="risk_on",
            risk_appetite="risk_on",
            confidence=0.85,
            source_provenance={"provider_name": "yfinance"},
        )
        lines = market_regime_summary(regime)
        self.assertEqual(len(lines), 1)
        self.assertIn("risk-on", lines[0])
        self.assertIn("0.85", lines[0])
        self.assertIn("yfinance", lines[0])

    def test_summary_empty_when_unknown(self) -> None:
        regime = build_market_regime(datetime(2026, 6, 8, tzinfo=timezone.utc))
        self.assertEqual(market_regime_summary(regime), [])
        self.assertEqual(market_regime_summary(None), [])


class CollectMarketRegimeTests(unittest.TestCase):
    def test_disabled_collector_makes_no_network_call(self) -> None:
        regime = collect_market_regime(enabled=False)
        self.assertEqual(regime.risk_appetite, "unknown")
        self.assertEqual(regime.confidence, 0.0)
        self.assertFalse(regime.is_known)


if __name__ == "__main__":
    unittest.main()
