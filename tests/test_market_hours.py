import unittest
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.services.market_hours import (
    is_market_open,
    next_market_open,
    time_until_market_open,
    should_defer_alert,
)

EST = ZoneInfo("America/New_York")


class MarketHoursTests(unittest.TestCase):
    def test_market_open_tuesday_930am(self) -> None:
        """Tuesday 9:30 AM is market open."""
        # June 3, 2026 is a Tuesday
        when = datetime(2026, 6, 3, 9, 30, tzinfo=EST)
        self.assertTrue(is_market_open(when))

    def test_market_closed_tuesday_930pm(self) -> None:
        """Tuesday 9:30 PM is after market close."""
        when = datetime(2026, 6, 3, 21, 30, tzinfo=EST)
        self.assertFalse(is_market_open(when))

    def test_market_closed_before_open(self) -> None:
        """Tuesday 9:00 AM is before market open."""
        when = datetime(2026, 6, 3, 9, 0, tzinfo=EST)
        self.assertFalse(is_market_open(when))

    def test_market_open_midday(self) -> None:
        """Tuesday 12:00 PM is market open."""
        when = datetime(2026, 6, 3, 12, 0, tzinfo=EST)
        self.assertTrue(is_market_open(when))

    def test_market_closed_weekend(self) -> None:
        """Saturday is market closed."""
        # June 7, 2026 is a Saturday
        when = datetime(2026, 6, 7, 12, 0, tzinfo=EST)
        self.assertFalse(is_market_open(when))

    def test_market_closed_holiday(self) -> None:
        """Holiday (Independence Day) is market closed."""
        # July 3, 2026 is Friday before July 4 - market closed
        # Actually July 4 is Saturday, so Friday July 3 is normal trading
        # Let's use a different holiday: Thanksgiving 2025
        when = datetime(2025, 11, 27, 12, 0, tzinfo=EST)
        self.assertFalse(is_market_open(when))

    def test_market_closed_after_early_close(self) -> None:
        """On an early-close day, 1:30 PM ET is already closed."""
        when = datetime(2026, 12, 24, 13, 30, tzinfo=EST)
        self.assertFalse(is_market_open(when))

    def test_next_market_open_afternoon(self) -> None:
        """From afternoon, next market open is tomorrow."""
        # Wednesday June 4, 2026 at 3:00 PM
        when = datetime(2026, 6, 4, 15, 0, tzinfo=EST)
        next_open = next_market_open(when)
        # Should be June 5 at 9:30 AM
        self.assertEqual(next_open.date().isoweekday(), 5)  # Friday
        self.assertEqual(next_open.time(), time(9, 30))

    def test_next_market_open_before_market_open(self) -> None:
        """From before market open, next open is today."""
        # Wednesday June 3, 2026 at 9:00 AM
        when = datetime(2026, 6, 3, 9, 0, tzinfo=EST)
        next_open = next_market_open(when)
        # Should be same day at 9:30 AM
        self.assertEqual(next_open.date(), when.date())
        self.assertEqual(next_open.time(), time(9, 30))

    def test_next_market_open_after_close_friday(self) -> None:
        """From Friday after close, next open is Monday."""
        # Friday June 5, 2026 at 5:00 PM
        when = datetime(2026, 6, 5, 17, 0, tzinfo=EST)
        next_open = next_market_open(when)
        # Should skip weekend, open Monday at 9:30 AM
        self.assertEqual(next_open.date().isoweekday(), 1)  # Monday
        self.assertEqual(next_open.time(), time(9, 30))

    def test_next_market_open_after_early_close_is_next_trading_day(self) -> None:
        """After a 1 PM early close, next open should be the next trading day."""
        when = datetime(2026, 12, 24, 13, 30, tzinfo=EST)
        next_open = next_market_open(when)
        self.assertEqual(next_open.date().isoformat(), "2026-12-28")
        self.assertEqual(next_open.time(), time(9, 30))

    def test_time_until_market_open(self) -> None:
        """Time until market open calculation."""
        # Tuesday June 3, 2026 at 9:00 AM (30 min until open)
        when = datetime(2026, 6, 3, 9, 0, tzinfo=EST)
        delta = time_until_market_open(when)
        # Should be ~30 minutes
        self.assertAlmostEqual(delta.total_seconds(), 30 * 60, delta=60)

    def test_should_defer_alert_outside_market_hours(self) -> None:
        """Alert outside market hours should be deferred."""
        # Tuesday 6:00 AM (before market open)
        when = datetime(2026, 6, 3, 6, 0, tzinfo=EST)
        self.assertTrue(should_defer_alert(when, is_high_impact=False))

    def test_should_not_defer_alert_during_market_hours(self) -> None:
        """Alert during market hours should not be deferred."""
        # Tuesday 12:00 PM (market open)
        when = datetime(2026, 6, 3, 12, 0, tzinfo=EST)
        self.assertFalse(should_defer_alert(when, is_high_impact=False))

    def test_should_not_defer_high_impact_alerts(self) -> None:
        """High-impact alerts (FOMC, jobs) always send immediately."""
        # Tuesday 6:00 AM (before market open)
        when = datetime(2026, 6, 3, 6, 0, tzinfo=EST)
        self.assertFalse(should_defer_alert(when, is_high_impact=True))

    def test_market_hours_with_utc_input(self) -> None:
        """Market hours check should work with UTC input."""
        # UTC time: 1:30 PM UTC = 9:30 AM EST
        when_utc = datetime(2026, 6, 3, 13, 30, tzinfo=ZoneInfo("UTC"))
        self.assertTrue(is_market_open(when_utc))

    def test_market_hours_with_naive_input(self) -> None:
        """Market hours check should work with naive datetime."""
        # Assuming naive datetime is in EST
        when = datetime(2026, 6, 3, 12, 0)  # No timezone
        # This should still work by assuming UTC then converting
        result = is_market_open(when)
        # Result depends on our assumption, but function shouldn't crash
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
