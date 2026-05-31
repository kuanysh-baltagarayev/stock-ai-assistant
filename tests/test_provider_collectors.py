from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from app.services.provider_collectors import (
    ProviderContract,
    load_market_data_collection_fixture,
    market_data_collection_from_payload,
)


class ProviderCollectorTests(unittest.TestCase):
    def test_provider_contract_roundtrips_registry_payload(self) -> None:
        contract = ProviderContract.from_name("yfinance")

        self.assertEqual(contract.name, "yfinance")
        self.assertEqual(contract.source_tier, "Tier 2")
        self.assertIn("historical_prices", contract.capability_list)
        self.assertEqual(contract.to_payload()["source_url"], "https://github.com/ranaroussi/yfinance")

    def test_fixture_loader_builds_normalized_collection(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "provider_collectors"
            / "yfinance_aapl.json"
        )

        collection = load_market_data_collection_fixture(fixture_path)
        market = collection.to_market_dict()

        self.assertEqual(collection.provider.name, "yfinance")
        self.assertEqual(collection.ticker, "AAPL")
        self.assertEqual(collection.price_source, "fast_info.last_price")
        self.assertEqual(collection.corporate_actions_policy, "raw_close_no_auto_adjustment")
        self.assertEqual(collection.data_quality["summary"], "ok")
        self.assertIsInstance(market["history"], pd.DataFrame)
        self.assertEqual(market["history"].iloc[-1]["Close"], 189.12)
        self.assertEqual(market["source_provenance"]["provider_name"], "yfinance")

    def test_payload_constructor_preserves_payload_shape(self) -> None:
        payload = {
            "ticker": "MSFT",
            "price": 101.0,
            "currency": "USD",
            "provider_name": "yfinance",
            "source_url": "https://github.com/ranaroussi/yfinance",
            "source_tier": "Tier 2",
            "data_category": "market_data",
            "extraction_method": "yfinance",
            "parser_version": "yfinance-0.2.65",
            "observed_at": "2026-05-28T00:00:00+00:00",
            "published_at": "2026-05-28T00:00:00+00:00",
            "fetched_at": "2026-05-28T00:00:00+00:00",
            "price_source": "history.close",
            "price_adjustment_policy": "raw_close",
            "corporate_actions_policy": "raw_close_no_auto_adjustment",
            "data_quality": {"summary": "ok"},
            "fx": None,
            "source_provenance": {"provider_name": "yfinance"},
            "history_rows": [],
        }

        collection = market_data_collection_from_payload(payload)

        self.assertEqual(collection.ticker, "MSFT")
        self.assertTrue(collection.history.empty)
        self.assertEqual(collection.source_url, "https://github.com/ranaroussi/yfinance")
        self.assertEqual(collection.to_market_dict()["price"], 101.0)
