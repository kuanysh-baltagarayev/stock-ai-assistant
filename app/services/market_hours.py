"""Market hours detection for alert timing.

Alerts sent outside trading hours are buffered and sent at market open.
High-impact economic events (FOMC, CPI) may trigger pre-market notifications.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.exchange_calendar import get_session_state

# US Eastern Time for market hours
EST = ZoneInfo("America/New_York")


def is_market_open(when: datetime | None = None) -> bool:
    """Check if market is currently open (regular trading hours).

    Args:
        when: Specific datetime to check. Defaults to now.

    Returns:
        True if during 9:30 AM - 4:00 PM EST on a trading day.
    """
    if when is None:
        when = datetime.now(EST)
    else:
        # Convert to EST if not already
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(EST)

    session = get_session_state(when)
    if session not in {"regular_open", "early_close"}:
        return False

    hour = when.hour
    minute = when.minute
    current_time = time(hour, minute)

    # Trading hours: 9:30 AM - 4:00 PM EST
    return time(9, 30) <= current_time < time(16, 0)


def next_market_open(when: datetime | None = None) -> datetime:
    """Get next market open time.

    Args:
        when: Specific datetime to check from. Defaults to now.

    Returns:
        Next market open datetime in EST.
    """
    if when is None:
        when = datetime.now(EST)
    else:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(EST)

    # Check if current time is before market open today
    market_open_time = time(9, 30)
    today = when.date()

    # Create a datetime at market open today to check session
    today_at_open = datetime.combine(today, market_open_time, tzinfo=EST)
    session = get_session_state(today_at_open)
    if session in {"regular_open", "early_close"} and when.time() < market_open_time:
        # Market opens today
        return today_at_open

    # Find next trading day and return its open time
    current = today + timedelta(days=1)
    while True:
        current_at_open = datetime.combine(current, market_open_time, tzinfo=EST)
        session = get_session_state(current_at_open)
        if session in {"regular_open", "early_close"}:
            return current_at_open
        current += timedelta(days=1)


def time_until_market_open(when: datetime | None = None) -> timedelta:
    """Time remaining until next market open.

    Args:
        when: Specific datetime to check from. Defaults to now.

    Returns:
        Timedelta to next market open.
    """
    if when is None:
        when = datetime.now(EST)
    else:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        when = when.astimezone(EST)

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
