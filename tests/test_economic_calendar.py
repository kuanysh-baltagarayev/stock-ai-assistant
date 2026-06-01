import unittest
from datetime import date

from app.services.economic_calendar import (
    EconomicEvent,
    event_impact_summary,
    events_for_date,
    next_event,
    upcoming_events,
)


class EconomicCalendarTests(unittest.TestCase):
    def test_upcoming_events_returns_list(self) -> None:
        result = upcoming_events(reference_date=date(2025, 1, 1), days_ahead=30)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_upcoming_events_filters_by_date(self) -> None:
        result = upcoming_events(reference_date=date(2025, 1, 1), days_ahead=15)
        # Should include Jan 10 (jobs) and Jan 15 (CPI) but not Feb 7
        result_dates = {e.event_date for e in result}
        self.assertIn(date(2025, 1, 10), result_dates)
        self.assertIn(date(2025, 1, 15), result_dates)
        self.assertNotIn(date(2025, 2, 7), result_dates)

    def test_upcoming_events_sorted_by_date(self) -> None:
        result = upcoming_events(reference_date=date(2025, 1, 1), days_ahead=60)
        dates = [e.event_date for e in result]
        self.assertEqual(dates, sorted(dates))

    def test_events_for_date_returns_matching_events(self) -> None:
        # Jan 10, 2025 is a jobs report day
        result = events_for_date(date(2025, 1, 10))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].event_type, "jobs")
        self.assertIn("Jobs Report", result[0].name)

    def test_events_for_date_returns_empty_list_for_no_events(self) -> None:
        result = events_for_date(date(2025, 1, 2))
        self.assertEqual(len(result), 0)

    def test_next_event_returns_first_upcoming(self) -> None:
        result = next_event(reference_date=date(2025, 1, 1))
        self.assertIsNotNone(result)
        self.assertEqual(result.event_date, date(2025, 1, 10))

    def test_next_event_filters_by_type(self) -> None:
        result = next_event(reference_date=date(2025, 1, 1), event_type="fomc_meeting")
        self.assertIsNotNone(result)
        self.assertEqual(result.event_type, "fomc_meeting")
        self.assertEqual(result.event_date, date(2025, 1, 28))

    def test_next_event_returns_none_for_future_dates(self) -> None:
        result = next_event(reference_date=date(2030, 1, 1))
        self.assertIsNone(result)

    def test_event_impact_summary_for_fomc(self) -> None:
        event = EconomicEvent(
            event_date=date(2025, 1, 28),
            event_type="fomc_meeting",
            name="FOMC Meeting",
            description="Test",
        )
        summary = event_impact_summary(event)
        self.assertIn("interest rate", summary.lower())

    def test_event_impact_summary_for_jobs(self) -> None:
        event = EconomicEvent(
            event_date=date(2025, 1, 10),
            event_type="jobs",
            name="Jobs Report",
            description="Test",
        )
        summary = event_impact_summary(event)
        self.assertIn("employment", summary.lower())

    def test_event_impact_summary_for_cpi(self) -> None:
        event = EconomicEvent(
            event_date=date(2025, 1, 15),
            event_type="cpi",
            name="CPI Release",
            description="Test",
        )
        summary = event_impact_summary(event)
        self.assertIn("inflation", summary.lower())

    def test_fomc_meetings_exist_for_2025(self) -> None:
        fomc_events = upcoming_events(
            reference_date=date(2025, 1, 1),
            days_ahead=365,
        )
        fomc_meetings = [e for e in fomc_events if e.event_type == "fomc_meeting"]
        self.assertEqual(len(fomc_meetings), 8)

    def test_jobs_reports_exist_for_2025(self) -> None:
        jobs_events = upcoming_events(
            reference_date=date(2025, 1, 1),
            days_ahead=365,
        )
        jobs_reports = [e for e in jobs_events if e.event_type == "jobs"]
        self.assertEqual(len(jobs_reports), 12)

    def test_cpi_releases_exist_for_2025(self) -> None:
        cpi_events = upcoming_events(
            reference_date=date(2025, 1, 1),
            days_ahead=365,
        )
        cpi_releases = [e for e in cpi_events if e.event_type == "cpi"]
        self.assertEqual(len(cpi_releases), 12)


if __name__ == "__main__":
    unittest.main()
