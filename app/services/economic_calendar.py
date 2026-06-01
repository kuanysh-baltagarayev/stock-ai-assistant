"""US economic calendar with key events.

Tracks important economic data releases and Fed meetings that impact markets.
Events are hardcoded for 2025-2026 based on official Fed and BLS schedules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class EconomicEvent:
    """An economic event with a date, type, and description."""

    event_date: date
    event_type: str  # "fomc_meeting", "cpi", "jobs", "gdp", "pce", "ppi"
    name: str
    description: str
    time_et: time | None = None
    importance: str = "medium"  # "low", "medium", "high"


_EVENTS_2025 = [
    # FOMC Meetings (8 per year, typically ~6 weeks apart)
    EconomicEvent(
        event_date=date(2025, 1, 28),
        event_type="fomc_meeting",
        name="FOMC Meeting (Jan)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 3, 18),
        event_type="fomc_meeting",
        name="FOMC Meeting (Mar)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 5, 6),
        event_type="fomc_meeting",
        name="FOMC Meeting (May)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 6, 17),
        event_type="fomc_meeting",
        name="FOMC Meeting (Jun)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 7, 29),
        event_type="fomc_meeting",
        name="FOMC Meeting (Jul)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 9, 16),
        event_type="fomc_meeting",
        name="FOMC Meeting (Sep)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 11, 4),
        event_type="fomc_meeting",
        name="FOMC Meeting (Nov)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 12, 16),
        event_type="fomc_meeting",
        name="FOMC Meeting (Dec)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    # Jobs Report (first Friday of each month at 8:30 AM ET)
    EconomicEvent(
        event_date=date(2025, 1, 10),
        event_type="jobs",
        name="Jobs Report (Jan)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 2, 7),
        event_type="jobs",
        name="Jobs Report (Feb)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 3, 7),
        event_type="jobs",
        name="Jobs Report (Mar)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 4, 4),
        event_type="jobs",
        name="Jobs Report (Apr)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 5, 2),
        event_type="jobs",
        name="Jobs Report (May)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 6, 6),
        event_type="jobs",
        name="Jobs Report (Jun)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 7, 3),
        event_type="jobs",
        name="Jobs Report (Jul)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 8, 1),
        event_type="jobs",
        name="Jobs Report (Aug)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 9, 5),
        event_type="jobs",
        name="Jobs Report (Sep)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 10, 3),
        event_type="jobs",
        name="Jobs Report (Oct)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 11, 7),
        event_type="jobs",
        name="Jobs Report (Nov)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 12, 5),
        event_type="jobs",
        name="Jobs Report (Dec)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    # CPI Release (mid-month at 8:30 AM ET)
    EconomicEvent(
        event_date=date(2025, 1, 15),
        event_type="cpi",
        name="CPI Release (Dec 2024)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 2, 12),
        event_type="cpi",
        name="CPI Release (Jan)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 3, 12),
        event_type="cpi",
        name="CPI Release (Feb)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 4, 11),
        event_type="cpi",
        name="CPI Release (Mar)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 5, 14),
        event_type="cpi",
        name="CPI Release (Apr)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 6, 11),
        event_type="cpi",
        name="CPI Release (May)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 7, 11),
        event_type="cpi",
        name="CPI Release (Jun)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 8, 13),
        event_type="cpi",
        name="CPI Release (Jul)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 9, 11),
        event_type="cpi",
        name="CPI Release (Aug)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 10, 10),
        event_type="cpi",
        name="CPI Release (Sep)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 11, 12),
        event_type="cpi",
        name="CPI Release (Oct)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2025, 12, 10),
        event_type="cpi",
        name="CPI Release (Nov)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
]

_EVENTS_2026 = [
    # FOMC Meetings
    EconomicEvent(
        event_date=date(2026, 1, 27),
        event_type="fomc_meeting",
        name="FOMC Meeting (Jan)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 3, 17),
        event_type="fomc_meeting",
        name="FOMC Meeting (Mar)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 5, 5),
        event_type="fomc_meeting",
        name="FOMC Meeting (May)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 6, 16),
        event_type="fomc_meeting",
        name="FOMC Meeting (Jun)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 7, 28),
        event_type="fomc_meeting",
        name="FOMC Meeting (Jul)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 9, 15),
        event_type="fomc_meeting",
        name="FOMC Meeting (Sep)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 11, 3),
        event_type="fomc_meeting",
        name="FOMC Meeting (Nov)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 12, 15),
        event_type="fomc_meeting",
        name="FOMC Meeting (Dec)",
        description="Federal Open Market Committee interest rate decision",
        time_et=time(14, 0),
        importance="high",
    ),
    # Jobs Report (first Friday of each month)
    EconomicEvent(
        event_date=date(2026, 1, 9),
        event_type="jobs",
        name="Jobs Report (Jan)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 2, 6),
        event_type="jobs",
        name="Jobs Report (Feb)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 3, 6),
        event_type="jobs",
        name="Jobs Report (Mar)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 4, 3),
        event_type="jobs",
        name="Jobs Report (Apr)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 5, 1),
        event_type="jobs",
        name="Jobs Report (May)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 6, 5),
        event_type="jobs",
        name="Jobs Report (Jun)",
        description="Employment Situation: nonfarm payroll, unemployment rate",
        time_et=time(8, 30),
        importance="high",
    ),
    # CPI Releases (sample for 2026 start)
    EconomicEvent(
        event_date=date(2026, 1, 14),
        event_type="cpi",
        name="CPI Release (Dec 2025)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
    EconomicEvent(
        event_date=date(2026, 2, 11),
        event_type="cpi",
        name="CPI Release (Jan)",
        description="Consumer Price Index: inflation measure",
        time_et=time(8, 30),
        importance="high",
    ),
]

_ALL_EVENTS = frozenset(_EVENTS_2025 + _EVENTS_2026)


def upcoming_events(reference_date: date | None = None, days_ahead: int = 30) -> list[EconomicEvent]:
    """Return upcoming economic events within days_ahead from reference_date.

    Args:
        reference_date: Start date for search (default: today)
        days_ahead: Number of days to look ahead (default: 30)

    Returns:
        Sorted list of events, earliest first.
    """
    from datetime import timedelta

    ref = reference_date or date.today()
    end_date = ref + timedelta(days=days_ahead)
    result = [
        e for e in _ALL_EVENTS
        if ref <= e.event_date <= end_date
    ]
    return sorted(result, key=lambda e: e.event_date)


def events_for_date(event_date: date) -> list[EconomicEvent]:
    """Return all events scheduled for a specific date."""
    return sorted(
        [e for e in _ALL_EVENTS if e.event_date == event_date],
        key=lambda e: e.time_et or time(0, 0),
    )


def next_event(reference_date: date | None = None, event_type: str | None = None) -> EconomicEvent | None:
    """Return the next upcoming economic event.

    Args:
        reference_date: Reference date (default: today)
        event_type: Filter by event type (e.g., "fomc_meeting", "jobs", "cpi")

    Returns:
        Next event, or None if none found.
    """
    ref = reference_date or date.today()
    candidates = [
        e for e in _ALL_EVENTS
        if e.event_date >= ref and (event_type is None or e.event_type == event_type)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda e: e.event_date)


def event_impact_summary(event: EconomicEvent) -> str:
    """Return a brief summary of how an event might impact markets."""
    impact = {
        "fomc_meeting": "Interest rate decision affects bond yields and equity valuations",
        "jobs": "Employment data impacts Fed policy and economic growth outlook",
        "cpi": "Inflation measure influences rate expectations and purchasing power",
        "gdp": "Economic growth data affects market sentiment and Fed policy",
        "pce": "Core inflation metric guides Fed interest rate decisions",
        "ppi": "Producer prices indicate inflation in the supply chain",
    }
    return impact.get(event.event_type, "Economic data release")
