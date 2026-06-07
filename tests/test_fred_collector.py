import unittest
from datetime import datetime, timezone

from app.services.fred_collector import (
    FredCollection,
    FredObservation,
    fetch_macro_indicators,
)


class FredCollectorTests(unittest.TestCase):
    def test_fetch_macro_indicators_returns_empty_without_api_key(self) -> None:
        collection = fetch_macro_indicators(api_key=None)
        self.assertIsNotNone(collection)
        self.assertEqual(len(collection.observations), 0)
        self.assertIsNotNone(collection.error)
        self.assertIn("FRED_API_KEY", collection.error)

    def test_collection_has_required_fields(self) -> None:
        now = datetime.now(timezone.utc)
        collection = FredCollection(
            observations=[
                FredObservation(
                    date="2026-06-01",
                    value=5.33,
                    series_id="FEDFUNDS",
                    series_name="Federal Funds Effective Rate (%)",
                )
            ],
            fetched_at=now,
        )
        self.assertEqual(collection.provider_name, "fred")
        self.assertEqual(collection.source_tier, "Tier 1")
        self.assertEqual(collection.data_category, "macro_indicators")

    def test_collection_to_snapshot_payload(self) -> None:
        now = datetime.now(timezone.utc)
        obs = FredObservation(
            date="2026-06-01",
            value=5.33,
            series_id="FEDFUNDS",
            series_name="Federal Funds Effective Rate (%)",
        )
        collection = FredCollection(observations=[obs], fetched_at=now)
        payload = collection.to_snapshot_payload()
        self.assertEqual(len(payload["observations"]), 1)
        self.assertEqual(payload["observations"][0]["series_id"], "FEDFUNDS")
        self.assertEqual(payload["observations"][0]["value"], 5.33)

    def test_collection_as_source_snapshot_dict(self) -> None:
        now = datetime.now(timezone.utc)
        obs = FredObservation(
            date="2026-06-01",
            value=5.33,
            series_id="FEDFUNDS",
            series_name="Federal Funds Effective Rate (%)",
        )
        collection = FredCollection(observations=[obs], fetched_at=now)
        snapshot_dict = collection.as_source_snapshot_dict()
        self.assertEqual(snapshot_dict["ticker"], "MACRO")
        self.assertEqual(snapshot_dict["provider_name"], "fred")
        self.assertEqual(snapshot_dict["source_tier"], "Tier 1")
        self.assertIsNotNone(snapshot_dict["payload_extra"])
        self.assertIsNotNone(snapshot_dict["source_provenance"])

    def test_latest_and_history_by_series(self) -> None:
        now = datetime.now(timezone.utc)
        # Newest-first order, mixed series, with one None value to skip.
        collection = FredCollection(
            observations=[
                FredObservation("2026-06-01", 5.33, "FEDFUNDS", "Federal Funds Effective Rate (%)"),
                FredObservation("2026-05-01", 5.10, "FEDFUNDS", "Federal Funds Effective Rate (%)"),
                FredObservation("2026-04-01", None, "FEDFUNDS", "Federal Funds Effective Rate (%)"),
                FredObservation("2026-06-01", 4.1, "UNRATE", "Unemployment Rate (%)"),
            ],
            fetched_at=now,
        )
        self.assertEqual(collection.latest_by_series(), {"FEDFUNDS": 5.33, "UNRATE": 4.1})
        history = collection.history_by_series()
        # Chronological (oldest-first), None dropped.
        self.assertEqual(history["FEDFUNDS"], [5.10, 5.33])
        self.assertEqual(history["UNRATE"], [4.1])

    def test_snapshot_dict_confidence_on_error(self) -> None:
        now = datetime.now(timezone.utc)
        collection = FredCollection(
            observations=[],
            fetched_at=now,
            error="API unavailable",
        )
        snapshot_dict = collection.as_source_snapshot_dict()
        self.assertEqual(snapshot_dict["confidence"], 0.0)
        self.assertIn("error", snapshot_dict["data_quality"]["summary"])

    def test_snapshot_dict_confidence_on_success(self) -> None:
        now = datetime.now(timezone.utc)
        collection = FredCollection(
            observations=[
                FredObservation(
                    date="2026-06-01",
                    value=5.33,
                    series_id="FEDFUNDS",
                    series_name="Federal Funds Effective Rate (%)",
                )
            ],
            fetched_at=now,
        )
        snapshot_dict = collection.as_source_snapshot_dict()
        self.assertEqual(snapshot_dict["confidence"], 1.0)
        self.assertEqual(snapshot_dict["data_quality"]["summary"], "ok")


if __name__ == "__main__":
    unittest.main()
