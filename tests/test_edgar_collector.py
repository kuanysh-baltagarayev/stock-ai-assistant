from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.edgar_collector import (
    edgar_collection_from_payload,
    fetch_recent_filings,
    reset_cik_map_cache,
    _parse_filings,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "edgar"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


class EdgarCollectorFixtureTests(unittest.TestCase):
    def test_edgar_collection_from_payload_full(self) -> None:
        payload = _load_fixture("aapl_filings.json")
        collection = edgar_collection_from_payload(payload)

        self.assertEqual(collection.ticker, "AAPL")
        self.assertEqual(collection.cik, 320193)
        self.assertEqual(collection.company_name, "Apple Inc.")
        self.assertEqual(len(collection.filings), 3)
        self.assertIsNone(collection.error)

        filing = collection.filings[0]
        self.assertEqual(filing.form_type, "10-Q")
        self.assertEqual(filing.filing_date, "2026-05-02")
        self.assertIn("sec.gov", filing.sec_url)

    def test_edgar_collection_from_payload_error_case(self) -> None:
        payload = _load_fixture("unknown_ticker.json")
        collection = edgar_collection_from_payload(payload)

        self.assertEqual(collection.ticker, "XXXXNOTREAL")
        self.assertIsNone(collection.cik)
        self.assertEqual(collection.filings, [])
        self.assertIsNotNone(collection.error)
        self.assertIn("XXXXNOTREAL", collection.error)

    def test_to_snapshot_payload_roundtrip(self) -> None:
        payload = _load_fixture("aapl_filings.json")
        collection = edgar_collection_from_payload(payload)
        snapshot = collection.to_snapshot_payload()

        self.assertEqual(snapshot["ticker"], "AAPL")
        self.assertEqual(len(snapshot["filings"]), 3)
        self.assertEqual(snapshot["source_tier"], "Tier 1")
        self.assertEqual(snapshot["data_category"], "sec_filings")

    def test_as_source_snapshot_dict_has_required_keys(self) -> None:
        payload = _load_fixture("aapl_filings.json")
        collection = edgar_collection_from_payload(payload)
        snap_dict = collection.as_source_snapshot_dict()

        for key in ("ticker", "provider_name", "source_url", "source_tier",
                    "data_category", "extraction_method", "parser_version",
                    "fetched_at", "confidence", "data_quality"):
            self.assertIn(key, snap_dict, f"Missing key: {key}")

        self.assertEqual(snap_dict["confidence"], 1.0)
        self.assertEqual(snap_dict["extraction_method"], "api")

    def test_error_collection_confidence_zero(self) -> None:
        payload = _load_fixture("unknown_ticker.json")
        collection = edgar_collection_from_payload(payload)
        snap_dict = collection.as_source_snapshot_dict()

        self.assertEqual(snap_dict["confidence"], 0.0)

    def test_fetched_at_timezone_aware(self) -> None:
        payload = _load_fixture("aapl_filings.json")
        collection = edgar_collection_from_payload(payload)
        self.assertIsNotNone(collection.fetched_at.tzinfo)


class EdgarParseFilingsTests(unittest.TestCase):
    def _make_recent(self) -> dict:
        return {
            "form": ["10-K", "8-K", "10-Q", "S-1", "EFFECT"],
            "filingDate": ["2025-11-01", "2025-10-15", "2025-08-01", "2025-07-01", "2025-06-01"],
            "accessionNumber": [
                "0000320193-25-100",
                "0000320193-25-101",
                "0000320193-25-102",
                "0000320193-25-103",
                "0000320193-25-104",
            ],
            "primaryDocDescription": ["10-K", "8-K", "10-Q", "S-1", ""],
            "primaryDocument": [
                "aapl-2025.htm",
                "aapl-8k.htm",
                "aapl-10q.htm",
                "",
                "",
            ],
        }

    def test_filters_irrelevant_forms(self) -> None:
        recent = self._make_recent()
        filings = _parse_filings(320193, recent, selected_forms={"8-K", "10-Q", "10-K"}, max_count=10)
        form_types = {f.form_type for f in filings}
        self.assertIn("10-K", form_types)
        self.assertIn("8-K", form_types)
        self.assertIn("10-Q", form_types)
        self.assertNotIn("EFFECT", form_types)

    def test_respects_max_count(self) -> None:
        recent = self._make_recent()
        filings = _parse_filings(320193, recent, selected_forms={"8-K", "10-Q", "10-K", "S-1"}, max_count=2)
        self.assertLessEqual(len(filings), 2)

    def test_filing_url_includes_cik_and_document(self) -> None:
        recent = self._make_recent()
        filings = _parse_filings(320193, recent, selected_forms={"10-K"}, max_count=5)
        self.assertEqual(len(filings), 1)
        self.assertIn("320193", filings[0].sec_url)
        self.assertIn("aapl-2025.htm", filings[0].sec_url)

    def test_filing_without_primary_doc_uses_browse_url(self) -> None:
        recent = {
            "form": ["S-1"],
            "filingDate": ["2025-07-01"],
            "accessionNumber": ["0000320193-25-103"],
            "primaryDocDescription": ["S-1"],
            "primaryDocument": [""],
        }
        filings = _parse_filings(320193, recent, selected_forms={"S-1"}, max_count=5)
        self.assertEqual(len(filings), 1)
        self.assertIn("browse-edgar", filings[0].sec_url)


class EdgarFetchWithMockTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_cik_map_cache()

    def tearDown(self) -> None:
        reset_cik_map_cache()

    def test_fetch_returns_error_on_cik_map_failure(self) -> None:
        with patch("app.services.edgar_collector._http_get_json", side_effect=OSError("network down")):
            result = fetch_recent_filings("AAPL")

        self.assertIsNotNone(result.error)
        self.assertIn("CIK map unavailable", result.error)
        self.assertEqual(result.filings, [])

    def test_fetch_returns_error_for_unknown_ticker(self) -> None:
        cik_map_response = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

        with patch("app.services.edgar_collector._http_get_json", return_value=cik_map_response):
            result = fetch_recent_filings("XXXXNOTREAL")

        self.assertIsNotNone(result.error)
        self.assertIn("XXXXNOTREAL", result.error)
        self.assertEqual(result.filings, [])
        self.assertIsNone(result.cik)

    def test_fetch_returns_error_on_submissions_failure(self) -> None:
        cik_map_response = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return cik_map_response
            raise OSError("submissions down")

        with patch("app.services.edgar_collector._http_get_json", side_effect=mock_get):
            result = fetch_recent_filings("AAPL")

        self.assertIsNotNone(result.error)
        self.assertIn("EDGAR submissions unavailable", result.error)
        self.assertEqual(result.cik, 320193)
        self.assertEqual(result.filings, [])

    def test_fetch_happy_path(self) -> None:
        cik_map_response = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        submissions_response = {
            "name": "Apple Inc.",
            "filings": {
                "recent": {
                    "form": ["10-K", "8-K"],
                    "filingDate": ["2025-11-01", "2025-10-15"],
                    "accessionNumber": ["0000320193-25-100", "0000320193-25-101"],
                    "primaryDocDescription": ["10-K", "8-K"],
                    "primaryDocument": ["aapl-2025.htm", "aapl-8k.htm"],
                }
            },
        }

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return cik_map_response
            return submissions_response

        with patch("app.services.edgar_collector._http_get_json", side_effect=mock_get):
            result = fetch_recent_filings("AAPL")

        self.assertIsNone(result.error)
        self.assertEqual(result.cik, 320193)
        self.assertEqual(result.company_name, "Apple Inc.")
        self.assertEqual(len(result.filings), 2)
        self.assertEqual(result.filings[0].form_type, "10-K")
