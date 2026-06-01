from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.exchange_calendar import (
    get_session_state,
    get_market_hours_info,
    is_trading_day,
    next_trading_day,
)

_ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_ET)


class SessionStateTests(unittest.TestCase):
    def test_regular_open(self) -> None:
        dt = _et(2026, 6, 1, 10, 0)  # Monday, regular session
        self.assertEqual(get_session_state(dt), "regular_open")

    def test_pre_market(self) -> None:
        dt = _et(2026, 6, 1, 8, 0)
        self.assertEqual(get_session_state(dt), "pre_market")

    def test_after_hours(self) -> None:
        dt = _et(2026, 6, 1, 17, 0)
        self.assertEqual(get_session_state(dt), "after_hours")

    def test_closed_late_night(self) -> None:
        dt = _et(2026, 6, 1, 22, 0)
        self.assertEqual(get_session_state(dt), "closed")

    def test_closed_early_morning(self) -> None:
        dt = _et(2026, 6, 1, 3, 0)
        self.assertEqual(get_session_state(dt), "closed")

    def test_weekend_saturday(self) -> None:
        dt = _et(2026, 5, 30, 10, 0)  # Saturday
        self.assertEqual(get_session_state(dt), "weekend")

    def test_weekend_sunday(self) -> None:
        dt = _et(2026, 5, 31, 10, 0)  # Sunday
        self.assertEqual(get_session_state(dt), "weekend")

    def test_holiday_new_year(self) -> None:
        dt = _et(2026, 1, 1, 10, 0)
        self.assertEqual(get_session_state(dt), "holiday")

    def test_holiday_independence_day(self) -> None:
        dt = _et(2026, 7, 3, 10, 0)  # Independence Day observed
        self.assertEqual(get_session_state(dt), "holiday")

    def test_holiday_thanksgiving_2026(self) -> None:
        dt = _et(2026, 11, 26, 11, 0)
        self.assertEqual(get_session_state(dt), "holiday")

    def test_holiday_christmas_2026(self) -> None:
        dt = _et(2026, 12, 25, 10, 0)
        self.assertEqual(get_session_state(dt), "holiday")

    def test_early_close_day_before_close(self) -> None:
        # 2026-12-24 Christmas Eve — closes at 13:00 ET
        # At 10:30 it should be regular_open (before early close time)
        dt = _et(2026, 12, 24, 10, 30)
        self.assertEqual(get_session_state(dt), "regular_open")

    def test_early_close_day_after_early_close(self) -> None:
        # At 13:30 ET on Christmas Eve → early_close window
        dt = _et(2026, 12, 24, 13, 30)
        self.assertEqual(get_session_state(dt), "early_close")

    def test_utc_input_works(self) -> None:
        # 2026-06-01 14:00 UTC = 10:00 ET → regular_open
        dt = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(get_session_state(dt), "regular_open")

    def test_market_open_boundary_inclusive(self) -> None:
        dt = _et(2026, 6, 1, 9, 30)
        self.assertEqual(get_session_state(dt), "regular_open")

    def test_market_close_boundary_exclusive(self) -> None:
        dt = _et(2026, 6, 1, 16, 0)
        self.assertEqual(get_session_state(dt), "after_hours")


class IsTradingDayTests(unittest.TestCase):
    def test_regular_monday(self) -> None:
        self.assertTrue(is_trading_day(date(2026, 6, 1)))

    def test_saturday_not_trading(self) -> None:
        self.assertFalse(is_trading_day(date(2026, 5, 30)))

    def test_sunday_not_trading(self) -> None:
        self.assertFalse(is_trading_day(date(2026, 5, 31)))

    def test_holiday_not_trading(self) -> None:
        self.assertFalse(is_trading_day(date(2026, 1, 1)))

    def test_early_close_is_still_trading(self) -> None:
        self.assertTrue(is_trading_day(date(2026, 12, 24)))


class NextTradingDayTests(unittest.TestCase):
    def test_friday_to_monday(self) -> None:
        # 2026-05-29 is a Friday
        self.assertEqual(next_trading_day(date(2026, 5, 29)), date(2026, 6, 1))

    def test_skips_holiday(self) -> None:
        # 2026-11-25 (Wednesday) → next is 2026-11-27 because 2026-11-26 is Thanksgiving
        self.assertEqual(next_trading_day(date(2026, 11, 25)), date(2026, 11, 27))

    def test_regular_weekday(self) -> None:
        self.assertEqual(next_trading_day(date(2026, 6, 1)), date(2026, 6, 2))


class MarketHoursInfoTests(unittest.TestCase):
    def test_returns_dict_with_required_keys(self) -> None:
        dt = _et(2026, 6, 1, 10, 0)
        info = get_market_hours_info(dt)
        for key in ("exchange", "state", "is_open", "is_holiday", "reference_time_et", "next_open"):
            self.assertIn(key, info)

    def test_is_open_when_regular(self) -> None:
        dt = _et(2026, 6, 1, 10, 0)
        info = get_market_hours_info(dt)
        self.assertTrue(info["is_open"])
        self.assertEqual(info["state"], "regular_open")

    def test_not_open_on_holiday(self) -> None:
        dt = _et(2026, 1, 1, 10, 0)
        info = get_market_hours_info(dt)
        self.assertFalse(info["is_open"])
        self.assertTrue(info["is_holiday"])

    def test_next_open_is_string(self) -> None:
        dt = _et(2026, 6, 1, 17, 0)
        info = get_market_hours_info(dt)
        self.assertIsInstance(info["next_open"], str)
        self.assertIn("09:30", info["next_open"])
