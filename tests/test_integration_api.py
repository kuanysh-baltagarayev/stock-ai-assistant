"""Integration tests for the FastAPI app via TestClient.

These tests run the real app with mocked market-data providers so they
are offline and fast.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from app.main import app
from starlette.testclient import TestClient


def _mock_get_market_data(*args, **kwargs):
    """Return minimal valid market data for offline tests."""
    dates = pd.bdate_range("2025-01-02", periods=252)
    close = pd.Series(
        [150.0 + i * 0.2 for i in range(252)],
        index=dates, name="Close", dtype=float,
    )
    history = pd.DataFrame({
        "Open": close * 0.99, "High": close * 1.02,
        "Low": close * 0.98, "Close": close,
        "Volume": 1_000_000,
    })
    return {
        "ticker": args[0].upper(),
        "price": 155.0,
        "currency": "USD",
        "price_adjustment_policy": "raw_close",
        "info": {
            "longName": "Test Corp",
            "sector": "Technology",
            "marketCap": 2_000_000_000_000,
            "trailingPE": 25.0,
            "forwardPE": 22.0,
            "revenueGrowth": 0.08,
            "profitMargins": 0.25,
            "debtToEquity": 1.5,
            "currentPrice": 155.0,
            "previousClose": 153.0,
            "earningsDate": [datetime(2026, 7, 15, tzinfo=timezone.utc)],
        },
        "history": history,
        "provider_name": "yfinance",
        "source_provenance": {
            "provider_name": "yfinance",
            "source_tier": "Tier 2",
            "data_category": "market_data",
            "extraction_method": "yfinance",
            "parser_version": "1.0",
            "observed_at": datetime.now(timezone.utc),
            "published_at": datetime.now(timezone.utc),
            "fetched_at": datetime.now(timezone.utc),
            "confidence": 0.95,
        },
        "data_quality": {
            "stale": False, "delayed": False, "estimated": False,
            "missing": False, "source_disagreed": False,
            "confidence": 0.95, "summary": "ok",
        },
        "fetched_at": datetime.now(timezone.utc),
    }


class ApiIntegrationTest(unittest.TestCase):
    """End-to-end API tests with mocked market data."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app"], "Stock AI Assistant")

    def test_root_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("endpoints", data)

    def test_ready_endpoint(self):
        response = self.client.get("/ready")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("database", data)

    @patch("app.services.scanner.get_market_data", side_effect=_mock_get_market_data)
    def test_analyze_ticker(self, mock_get_market_data):
        response = self.client.get("/analyze/AAPL")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["ticker"], "AAPL")
        self.assertIn("final_score", str(data.get("scores", {})))
        self.assertIn("explanation", data)
        self.assertIn("operation_notes", data)
        self.assertNotIn("OPENAI_API_KEY", str(data.get("explanation", "")))

    @patch("app.services.scanner.get_market_data", side_effect=_mock_get_market_data)
    def test_analyze_ticker_404(self, mock_get_market_data):
        """Unknown ticker should return 404.

        We test this by making get_market_data raise a MarketDataError
        with status_code=404.
        """
        from app.services.market_data import MarketDataError

        def _raise_404(*args, **kwargs):
            raise MarketDataError("No data for UNKNOWN", status_code=404)

        with patch("app.services.scanner.get_market_data", side_effect=_raise_404):
            response = self.client.get("/analyze/UNKNOWN")
            self.assertEqual(response.status_code, 404)
            data = response.json()
            self.assertIn("detail", data)

    @patch("app.services.scanner.get_market_data", side_effect=_mock_get_market_data)
    def test_scan_tickers(self, mock_get_market_data):
        response = self.client.post(
            "/scan",
            json={"tickers": ["AAPL", "MSFT"]},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertIn("summary", data)
        self.assertGreaterEqual(len(data["results"]), 1)

    def test_coverage_endpoint(self):
        response = self.client.get("/coverage")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("supported_markets", data)
        self.assertIn("known_gaps", data)

    def test_scan_validation_empty_tickers(self):
        response = self.client.post("/scan", json={"tickers": []})
        self.assertEqual(response.status_code, 422)  # Validation error

    def test_scan_validation_too_many(self):
        response = self.client.post(
            "/scan",
            json={"tickers": ["AAPL"] * 101},
        )
        self.assertEqual(response.status_code, 422)  # max 100
