"""US exchange session calendar.

Provides session state classification (holiday, early-close, regular-open,
pre-market, after-hours, closed/weekend) for NYSE/NASDAQ.

Holidays and early-close dates are hardcoded for 2025 and 2026.
Regular trading hours: 09:30–16:00 ET.
Pre-market: 04:00–09:30 ET. After-hours: 16:00–20:00 ET.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# NYSE holidays: market fully closed
_NYSE_HOLIDAYS: frozenset[date] = frozenset(
    [
        # 2025
        date(2025, 1, 1),   # New Year's Day
        date(2025, 1, 20),  # MLK Day
        date(2025, 2, 17),  # Presidents' Day
        date(2025, 4, 18),  # Good Friday
        date(2025, 5, 26),  # Memorial Day
        date(2025, 6, 19),  # Juneteenth
        date(2025, 7, 4),   # Independence Day
        date(2025, 9, 1),   # Labor Day
        date(2025, 11, 27), # Thanksgiving
        date(2025, 12, 25), # Christmas Day
        # 2026
        date(2026, 1, 1),   # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents' Day
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),   # Independence Day (observed)
        date(2026, 9, 7),   # Labor Day
        date(2026, 11, 26), # Thanksgiving
        date(2026, 12, 25), # Christmas Day
    ]
)

# Early-close days: market closes at 13:00 ET
_NYSE_EARLY_CLOSES: frozenset[date] = frozenset(
    [
        # 2025
        date(2025, 7, 3),   # Day before Independence Day
        date(2025, 11, 28), # Day after Thanksgiving
        date(2025, 12, 24), # Christmas Eve
        # 2026
        date(2026, 11, 27), # Day after Thanksgiving
        date(2026, 12, 24), # Christmas Eve
    ]
)

_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)
_EARLY_CLOSE = time(13, 0)
_PRE_MARKET_START = time(4, 0)
_AFTER_HOURS_END = time(20, 0)


def get_session_state(dt: datetime, exchange: str = "NYSE") -> str:
    """Return the session state for a given UTC datetime.

    Returns one of:
      "holiday"      - market fully closed (public holiday)
      "weekend"      - Saturday or Sunday
      "early_close"  - early-close day; returns "early_close" during 13:00-16:00 ET
      "regular_open" - 09:30-16:00 ET on a normal trading day
      "pre_market"   - 04:00-09:30 ET
      "after_hours"  - 16:00-20:00 ET
      "closed"       - outside all trading windows on a weekday
    """
    et = dt.astimezone(_ET) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(_ET)
    local_date = et.date()
    local_time = et.time()

    if local_date in _NYSE_HOLIDAYS:
        return "holiday"

    weekday = et.weekday()
    if weekday >= 5:
        return "weekend"

    is_early = local_date in _NYSE_EARLY_CLOSES
    close_time = _EARLY_CLOSE if is_early else _MARKET_CLOSE

    if _MARKET_OPEN <= local_time < close_time:
        return "regular_open"

    if is_early and close_time <= local_time < _MARKET_CLOSE:
        return "early_close"

    if _PRE_MARKET_START <= local_time < _MARKET_OPEN:
        return "pre_market"

    if _MARKET_CLOSE <= local_time < _AFTER_HOURS_END:
        return "after_hours"

    return "closed"


def is_trading_day(d: date, exchange: str = "NYSE") -> bool:
    """Return True if the given date is a regular NYSE trading day."""
    if d in _NYSE_HOLIDAYS:
        return False
    return d.weekday() < 5


def next_trading_day(d: date, exchange: str = "NYSE") -> date:
    """Return the next NYSE trading day after the given date."""
    candidate = d + timedelta(days=1)
    while not is_trading_day(candidate, exchange):
        candidate += timedelta(days=1)
    return candidate


def get_market_hours_info(dt: datetime | None = None, exchange: str = "NYSE") -> dict:
    """Return a dict describing current session state and next open/close times."""
    ref = dt if dt is not None else datetime.now(timezone.utc)
    state = get_session_state(ref, exchange)
    et = ref.astimezone(_ET) if ref.tzinfo else ref.replace(tzinfo=timezone.utc).astimezone(_ET)
    local_date = et.date()

    is_early = local_date in _NYSE_EARLY_CLOSES
    close_time = _EARLY_CLOSE if is_early else _MARKET_CLOSE

    if state in {"holiday", "weekend", "closed", "early_close", "after_hours"}:
        next_day = next_trading_day(local_date, exchange)
        next_open_dt = datetime(
            next_day.year, next_day.month, next_day.day, 9, 30, tzinfo=_ET
        )
    else:
        next_open_dt = et.replace(hour=9, minute=30, second=0, microsecond=0)

    if state == "regular_open":
        market_close_dt: datetime | None = et.replace(
            hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0
        )
    else:
        market_close_dt = None

    return {
        "exchange": exchange,
        "state": state,
        "is_open": state == "regular_open",
        "is_holiday": state == "holiday",
        "is_early_close": is_early and is_trading_day(local_date, exchange),
        "reference_time_et": et.isoformat(),
        "next_open": next_open_dt.isoformat(),
        "market_close": market_close_dt.isoformat() if market_close_dt else None,
    }
