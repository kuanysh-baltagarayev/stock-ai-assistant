"""Market hours detection for alert timing.

Alerts sent outside trading hours are buffered and sent at market open.
High-impact economic events (FOMC, CPI) may trigger pre-market notifications.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.exchange_calendar import get_session_state, next_trading_day

# US Eastern Time for market hours
EST = ZoneInfo("America/New_York")


def _to_est(when: datetime | None) -> datetime:
    if when is None:
        return datetime.now(EST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(EST)


def is_market_open(when: datetime | None = None) -> bool:
    """Check if market is currently open (regular trading hours).

    Args:
        when: Specific datetime to check. Defaults to now.

    Returns:
        True if during 9:30 AM - 4:00 PM EST on a trading day.
    """
    return get_session_state(_to_est(when)) == "regular_open"


def next_market_open(when: datetime | None = None) -> datetime:
    """Get next market open time.

    Args:
        when: Specific datetime to check from. Defaults to now.

    Returns:
        Next market open datetime in EST.
    """
    when = _to_est(when)
    market_open_today = when.replace(hour=9, minute=30, second=0, microsecond=0)
    session = get_session_state(when)

    if session in {"closed", "pre_market"} and when.time() < market_open_today.time():
        return market_open_today

    next_day = next_trading_day(when.date())
    return datetime(next_day.year, next_day.month, next_day.day, 9, 30, tzinfo=EST)


def time_until_market_open(when: datetime | None = None) -> timedelta:
    """Time remaining until next market open.

    Args:
        when: Specific datetime to check from. Defaults to now.

    Returns:
        Timedelta to next market open.
    """
    when = _to_est(when)
    return next_market_open(when) - when


def should_defer_alert(
    when: datetime | None = None, is_high_impact: bool = False
) -> bool:
    """Check if alert should be deferred to market open.

    Args:
        when: Specific datetime to check. Defaults to now.
        is_high_impact: If True (FOMC, jobs report), send immediately.

    Returns:
        True if alert should be buffered until market open.
    """
    if is_high_impact:
        # Always send high-impact economic events immediately
        return False

    return not is_market_open(when)
