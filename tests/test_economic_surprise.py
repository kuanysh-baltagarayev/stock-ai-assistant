import unittest
from datetime import date

from app.services.economic_surprise import (
    calculate_surprise,
    alert_text,
    surprise_alert_summary,
)


class EconomicSurpriseTests(unittest.TestCase):
    def test_calculate_surprise_positive(self) -> None:
        surprise = calculate_surprise(
            event_type="jobs",
            event_name="Jobs Report (Jan)",
            expected=200000,
            actual=250000,
        )
        self.assertGreater(surprise.surprise_pct or 0, 0)
        self.assertEqual(surprise.direction, "positive")
        self.assertAlmostEqual(surprise.surprise_pct, 25.0, places=1)

    def test_calculate_surprise_negative(self) -> None:
        surprise = calculate_surprise(
            event_type="cpi",
            event_name="CPI Release (Jan)",
            expected=0.3,
            actual=0.1,
        )
        self.assertLess(surprise.surprise_pct or 0, 0)
        self.assertEqual(surprise.direction, "negative")
        self.assertAlmostEqual(surprise.surprise_pct, -66.7, places=1)

    def test_calculate_surprise_extreme_magnitude(self) -> None:
        surprise = calculate_surprise(
            event_type="jobs",
            event_name="Jobs Report",
            expected=150000,
            actual=50000,  # Huge miss
        )
        self.assertEqual(surprise.surprise_magnitude, "extreme")
        self.assertTrue(surprise.trading_relevant)

    def test_calculate_surprise_high_magnitude(self) -> None:
        surprise = calculate_surprise(
            event_type="cpi",
            event_name="CPI Release",
            expected=0.3,
            actual=0.22,  # ~26% miss - high magnitude for inflation
        )
        self.assertEqual(surprise.surprise_magnitude, "high")
        self.assertTrue(surprise.trading_relevant)

    def test_calculate_surprise_medium_magnitude(self) -> None:
        surprise = calculate_surprise(
            event_type="ppi",
            event_name="PPI Release",
            expected=0.2,
            actual=0.24,  # 20% beat
        )
        self.assertEqual(surprise.surprise_magnitude, "medium")
        self.assertTrue(surprise.trading_relevant)

    def test_calculate_surprise_low_magnitude(self) -> None:
        surprise = calculate_surprise(
            event_type="pce",
            event_name="PCE Release",
            expected=0.3,
            actual=0.305,  # 1.7% beat - low magnitude for inflation
        )
        self.assertEqual(surprise.surprise_magnitude, "low")
        self.assertFalse(surprise.trading_relevant)

    def test_calculate_surprise_no_surprise(self) -> None:
        surprise = calculate_surprise(
            event_type="gdp",
            event_name="GDP Release",
            expected=2.5,
            actual=2.5,
        )
        # When actual equals expected, surprise_pct is 0
        self.assertIsNotNone(surprise.surprise_pct)
        self.assertEqual(surprise.surprise_pct, 0.0)
        self.assertFalse(surprise.trading_relevant)

    def test_alert_text_trading_relevant(self) -> None:
        surprise = calculate_surprise(
            event_type="jobs",
            event_name="Jobs Report (Jan)",
            expected=200000,
            actual=100000,
        )
        alert = alert_text(surprise)
        self.assertIsNotNone(alert)
        self.assertIn("Jobs Report", alert)
        self.assertIn("50.0%", alert)
        self.assertIn("extreme", alert)

    def test_alert_text_not_trading_relevant(self) -> None:
        surprise = calculate_surprise(
            event_type="pce",
            event_name="PCE Release",
            expected=0.3,
            actual=0.31,
        )
        alert = alert_text(surprise)
        self.assertIsNone(alert)

    def test_surprise_alert_summary_empty(self) -> None:
        surprises = [
            calculate_surprise("pce", "PCE", 0.3, 0.305),  # Not relevant (low)
            calculate_surprise("ppi", "PPI", 0.2, 0.204),  # Not relevant (low)
        ]
        alerts = surprise_alert_summary(surprises)
        self.assertEqual(len(alerts), 0)

    def test_surprise_alert_summary_multiple(self) -> None:
        surprises = [
            calculate_surprise("jobs", "Jobs", 200000, 100000),  # Extreme (50% miss)
            calculate_surprise("cpi", "CPI", 0.3, 0.1),  # Extreme (66.7% miss, inflation)
            calculate_surprise("pce", "PCE", 0.3, 0.305),  # Not relevant
        ]
        alerts = surprise_alert_summary(surprises)
        self.assertEqual(len(alerts), 2)
        # Both should be extreme and trading_relevant, CPI should come first (66.7% > 50%)
        self.assertTrue(any("CPI" in alert for alert in alerts))

    def test_market_impact_text_jobs_positive(self) -> None:
        surprise = calculate_surprise(
            event_type="jobs",
            event_name="Jobs Report",
            expected=150000,
            actual=200000,
        )
        alert = alert_text(surprise)
        self.assertIsNotNone(alert)
        self.assertIn("equity support", alert)
        self.assertIn("USD strength", alert)

    def test_market_impact_text_cpi_negative(self) -> None:
        surprise = calculate_surprise(
            event_type="cpi",
            event_name="CPI Release",
            expected=0.3,
            actual=0.1,
        )
        alert = alert_text(surprise)
        self.assertIsNotNone(alert)
        self.assertIn("Lower inflation", alert)
        self.assertIn("growth stocks support", alert)

    def test_surprise_description(self) -> None:
        surprise = calculate_surprise(
            event_type="jobs",
            event_name="Jobs Report (Jan)",
            expected=200000,
            actual=250000,
        )
        self.assertIn("beat expectations", surprise.description)
        self.assertIn("25.0%", surprise.description)


if __name__ == "__main__":
    unittest.main()
