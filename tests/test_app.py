from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import ConfigurationError, PROJECT_ROOT, get_settings, resolve_database_url
from app.api.routes import health, root
from app.database import Base
from app.diagnostics import build_startup_diagnostics, enforce_local_api_policy
from app.migrations import apply_migrations
from app.models import AnalysisSnapshot
from app.models import InstrumentRegistry
from app.models import ProviderRegistry
from app.models import SourceSnapshot
from app.main import app
from app.schemas import (
    AnalyzeResponse,
    Fundamentals,
    ScanRequest,
    Scores,
    TechnicalIndicators,
)
from app.services.ai_explainer import explain_analysis
from app.services.edgar_collector import EdgarCollection, EdgarFiling
from app.services import market_data
from app.services.runtime_budget import reset_runtime_budgets
from app.services.scanner import analyze_ticker, scan_tickers


def make_analysis(ticker: str, final_score: float) -> AnalyzeResponse:
    return AnalyzeResponse(
        ticker=ticker,
        generated_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
        price=100.0,
        currency="USD",
        fundamentals=Fundamentals(company_name=f"{ticker} Corp"),
        technicals=TechnicalIndicators(),
        scores=Scores(
            momentum_score=50.0,
            valuation_score=50.0,
            risk_score=50.0,
            final_score=final_score,
        ),
        recommendation="NEUTRAL",
        short_reason=f"{ticker} short reason",
        explanation=f"{ticker} explanation",
        event_calendar=None,
        sec_filings=None,
    )


class AppSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_budgets()
        market_data.clear_market_data_cache()

    def tearDown(self) -> None:
        reset_runtime_budgets()
        market_data.clear_market_data_cache()

    def test_root_and_health_smoke(self) -> None:
        with (
            patch(
                "app.services.telegram_bot.TelegramBotService.start",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.telegram_bot.TelegramBotService.stop",
                new=AsyncMock(return_value=None),
            ),
            TestClient(app),
        ):
            root_response = root()
            health_response = health()

        self.assertEqual(root_response.app, "Stock AI Assistant")
        self.assertIn("/analyze/{ticker}", root_response.endpoints)
        self.assertIn("/ready", root_response.endpoints)
        self.assertIn("/providers", root_response.endpoints)
        self.assertIn("/providers/{name}", root_response.endpoints)
        self.assertIn("/coverage", root_response.endpoints)
        self.assertEqual(health_response.status, "ok")
        self.assertEqual(health_response.app, "Stock AI Assistant")

    def test_scan_request_normalizes_and_deduplicates_tickers(self) -> None:
        request = ScanRequest(tickers=[" aapl ", "MSFT", "aapl", "", "  nvda "])

        self.assertEqual(request.tickers, ["AAPL", "MSFT", "NVDA"])

    def test_resolve_database_url_uses_project_root_for_relative_sqlite_paths(self) -> None:
        resolved = resolve_database_url("sqlite:///./stock_ai_assistant.db")

        self.assertTrue(resolved.startswith("sqlite:///"))
        self.assertIn(str(Path(PROJECT_ROOT / "stock_ai_assistant.db").resolve()), resolved)

    def test_market_data_retries_download_before_succeeding(self) -> None:
        history = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.date_range("2026-05-25", periods=3, tz="UTC"),
        )

        settings = SimpleNamespace(
            market_data_timeout_seconds=5.0,
            market_data_max_attempts=3,
            market_data_retry_backoff_seconds=0.0,
        )

        with (
            patch("app.services.market_data.get_settings", return_value=settings),
            patch("app.services.market_data.yf.download", side_effect=[RuntimeError("temporary"), history]),
            patch("app.services.market_data.yf.Ticker", return_value=SimpleNamespace()),
            patch("app.services.market_data._safe_info", return_value={}),
            patch("app.services.market_data._safe_fast_info", return_value={}),
            patch("app.services.market_data.time.sleep"),
        ):
            data = market_data.get_market_data("aapl")

        self.assertEqual(data["ticker"], "AAPL")
        self.assertEqual(data["price"], 102.0)
        self.assertEqual(len(data["history"]), 3)

    def test_market_data_reuses_cache_without_provider_calls(self) -> None:
        history = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.date_range("2026-05-25", periods=3, tz="UTC"),
        )
        stock = SimpleNamespace(info={}, fast_info={})
        settings = SimpleNamespace(
            market_data_timeout_seconds=5.0,
            market_data_max_attempts=1,
            market_data_retry_backoff_seconds=0.0,
            market_data_cache_ttl_seconds=3600,
            provider_call_budget=3,
        )

        with (
            patch("app.services.market_data.get_settings", return_value=settings),
            patch("app.services.market_data.yf.download", return_value=history) as download_mock,
            patch("app.services.market_data.yf.Ticker", return_value=stock),
        ):
            first = market_data.get_market_data("aapl")
            second = market_data.get_market_data("aapl")

        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["price"], 102.0)
        download_mock.assert_called_once()

    def test_market_data_provider_budget_exhaustion_returns_429(self) -> None:
        settings = SimpleNamespace(
            market_data_timeout_seconds=5.0,
            market_data_max_attempts=1,
            market_data_retry_backoff_seconds=0.0,
            market_data_cache_ttl_seconds=0,
            provider_call_budget=0,
        )

        with (
            patch("app.services.market_data.get_settings", return_value=settings),
            patch("app.services.market_data.yf.download") as download_mock,
        ):
            with self.assertRaises(market_data.MarketDataError) as exc:
                market_data.get_market_data("aapl")

        self.assertEqual(exc.exception.status_code, 429)
        self.assertIn("Provider call budget exhausted", str(exc.exception))
        download_mock.assert_not_called()

    def test_market_data_records_provider_success(self) -> None:
        history = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.date_range("2026-05-25", periods=3, tz="UTC"),
        )

        settings = SimpleNamespace(
            market_data_timeout_seconds=5.0,
            market_data_max_attempts=3,
            market_data_retry_backoff_seconds=0.0,
        )

        with (
            patch("app.services.market_data.get_settings", return_value=settings),
            patch("app.services.market_data.yf.download", return_value=history),
            patch("app.services.market_data.yf.Ticker", return_value=SimpleNamespace()),
            patch("app.services.market_data._safe_info", return_value={}),
            patch("app.services.market_data._safe_fast_info", return_value={}),
            patch("app.services.market_data.record_provider_success") as record_success,
            patch("app.services.market_data.record_provider_failure") as record_failure,
        ):
            data = market_data.get_market_data("aapl", db=SimpleNamespace())

        self.assertEqual(data["ticker"], "AAPL")
        record_success.assert_called_once()
        record_failure.assert_not_called()
        self.assertEqual(record_success.call_args.kwargs["name"], "yfinance")
        self.assertEqual(record_success.call_args.kwargs["source_tier"], "Tier 2")
        self.assertEqual(
            record_success.call_args.kwargs["capability_list"],
            ["historical_prices", "company_profile", "fast_info"],
        )

    def test_market_data_records_provider_failure(self) -> None:
        settings = SimpleNamespace(
            market_data_timeout_seconds=5.0,
            market_data_max_attempts=1,
            market_data_retry_backoff_seconds=0.0,
        )

        with (
            patch("app.services.market_data.get_settings", return_value=settings),
            patch("app.services.market_data.yf.download", side_effect=RuntimeError("temporary")),
            patch("app.services.market_data.record_provider_success") as record_success,
            patch("app.services.market_data.record_provider_failure") as record_failure,
        ):
            with self.assertRaises(market_data.MarketDataError):
                market_data.get_market_data("aapl", db=SimpleNamespace())

        record_success.assert_not_called()
        record_failure.assert_called_once()
        self.assertEqual(record_failure.call_args.kwargs["name"], "yfinance")
        self.assertEqual(record_failure.call_args.kwargs["failure_mode"], "unavailable")

    def test_market_data_flags_stale_and_disagreement(self) -> None:
        history = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"], utc=True),
        )

        settings = SimpleNamespace(
            market_data_timeout_seconds=5.0,
            market_data_max_attempts=1,
            market_data_retry_backoff_seconds=0.0,
        )

        with (
            patch("app.services.market_data.get_settings", return_value=settings),
            patch("app.services.market_data.yf.download", return_value=history),
            patch("app.services.market_data.yf.Ticker", return_value=SimpleNamespace()),
            patch(
                "app.services.market_data._safe_info",
                return_value={
                    "currentPrice": 122.0,
                    "regularMarketPrice": 121.5,
                    "currency": "USD",
                },
            ),
            patch("app.services.market_data._safe_fast_info", return_value={"last_price": 120.0}),
        ):
            data = market_data.get_market_data("aapl")

        self.assertEqual(data["price"], 120.0)
        self.assertEqual(data["price_source"], "fast_info.last_price")
        self.assertTrue(data["data_quality"]["stale"])
        self.assertTrue(data["data_quality"]["delayed"])
        self.assertTrue(data["data_quality"]["source_disagreed"])
        self.assertEqual(data["data_quality"]["confidence"], 0.5)
        self.assertEqual(data["price_adjustment_policy"], "raw_close")
        self.assertEqual(data["fx"]["base_currency"], "USD")

    def test_runtime_budgets_persist_across_module_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "budgets.db"
            engine = create_engine(f"sqlite:///{db_path}")
            self.addCleanup(engine.dispose)
            apply_migrations(engine)

            with patch("app.database.engine", engine):
                from app.services import runtime_budget

                runtime_budget.reset_runtime_budgets(clear_persistent=True)
                first = runtime_budget.consume_runtime_budget("openai_calls", 3, amount=2)
                runtime_budget._COUNTERS.clear()
                snapshot = runtime_budget.runtime_budget_snapshot("openai_calls", 3)
                second = runtime_budget.consume_runtime_budget("openai_calls", 3)

            self.assertEqual(first.used, 2)
            self.assertEqual(first.remaining, 1)
            self.assertEqual(snapshot.used, 2)
            self.assertEqual(snapshot.remaining, 1)
            self.assertEqual(second.used, 3)
            self.assertEqual(second.remaining, 0)

    def test_market_data_rejects_empty_ticker(self) -> None:
        with self.assertRaises(market_data.InvalidTickerError):
            market_data.normalize_ticker("   ")

    def test_analyze_ticker_builds_response_without_network(self) -> None:
        market = {
            "ticker": "AAPL",
            "price": 189.12,
            "currency": "USD",
            "history": pd.DataFrame({"Close": [100.0, 101.0, 102.0]}),
            "info": {},
        }
        fundamentals = Fundamentals(company_name="Apple Inc.", sector="Technology")
        technicals = TechnicalIndicators(change_1d_pct=1.0)
        scoring = SimpleNamespace(
            scores=Scores(
                momentum_score=60.0,
                valuation_score=55.0,
                risk_score=35.0,
                final_score=62.5,
            ),
            recommendation="NEUTRAL",
            short_reason="Neutral: sample reason.",
            reasons=["price is above MA50"],
        )
        edgar_collection = EdgarCollection(
            ticker="AAPL",
            cik=320193,
            company_name="Apple Inc.",
            filings=[
                EdgarFiling(
                    form_type="10-Q",
                    filing_date="2026-04-30",
                    accession_number="0000320193-26-000010",
                    description="Quarterly report",
                    sec_url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-20260329.htm",
                )
            ],
            fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )

        with (
            patch("app.services.scanner.get_market_data", return_value=market),
            patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
            patch("app.services.scanner.calculate_indicators", return_value=technicals),
            patch("app.services.scanner.score_stock", return_value=scoring),
            patch("app.services.scanner.explain_analysis", return_value="Mock explanation"),
            patch("app.services.scanner.fetch_recent_filings", return_value=edgar_collection),
        ):
            response = analyze_ticker("aapl", db=None, use_ai_explanation=True)

        self.assertEqual(response.ticker, "AAPL")
        self.assertEqual(response.price, 189.12)
        self.assertEqual(response.explanation, "Mock explanation")
        self.assertIsNotNone(response.generated_at.tzinfo)
        self.assertIsNotNone(response.sec_filings)
        self.assertEqual(response.sec_filings.recent_filings[0].form_type, "10-Q")
        self.assertTrue(any("SEC filing" in note for note in response.operation_notes))

    def test_analyze_ticker_adds_operation_notes_for_openai_fallback(self) -> None:
        market = {
            "ticker": "AAPL",
            "price": 189.12,
            "currency": "USD",
            "history": pd.DataFrame({"Close": [100.0, 101.0, 102.0]}),
            "info": {},
            "data_quality": {"summary": "ok"},
        }
        fundamentals = Fundamentals(company_name="Apple Inc.", sector="Technology")
        technicals = TechnicalIndicators(change_1d_pct=1.0)
        scoring = SimpleNamespace(
            scores=Scores(
                momentum_score=60.0,
                valuation_score=55.0,
                risk_score=35.0,
                final_score=62.5,
            ),
            recommendation="NEUTRAL",
            short_reason="Neutral: sample reason.",
            reasons=["price is above MA50"],
        )

        with (
            patch("app.services.scanner.get_settings", return_value=SimpleNamespace(openai_api_key=None, analysis_snapshot_retention_count=50, analysis_snapshot_retention_days=365)),
            patch("app.services.scanner.get_market_data", return_value=market),
            patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
            patch("app.services.scanner.calculate_indicators", return_value=technicals),
            patch("app.services.scanner.score_stock", return_value=scoring),
            patch("app.services.scanner.explain_analysis", return_value="Mock explanation"),
            patch("app.services.scanner._build_market_session", return_value=None),
        ):
            response = analyze_ticker("aapl", db=None, use_ai_explanation=True)

        self.assertTrue(
            any("OpenAI explanation is disabled" in note for note in response.operation_notes),
            f"Expected OpenAI message in operation_notes, got: {response.operation_notes}"
        )

    def test_analyze_ticker_recent_8k_increases_risk_score(self) -> None:
        market = {
            "ticker": "AAPL",
            "price": 189.12,
            "currency": "USD",
            "history": pd.DataFrame({"Close": [100.0, 101.0, 102.0]}),
            "info": {},
            "data_quality": {"summary": "ok"},
        }
        fundamentals = Fundamentals(company_name="Apple Inc.", sector="Technology")
        technicals = TechnicalIndicators(
            change_1d_pct=1.0,
            change_1m_pct=8.0,
            change_6m_pct=20.0,
            moving_average_50=180.0,
            moving_average_200=170.0,
            rsi=55.0,
            volatility_pct=22.0,
            max_drawdown_pct=-12.0,
        )

        with (
            patch("app.services.scanner.get_settings", return_value=SimpleNamespace(openai_api_key=None, analysis_snapshot_retention_count=50, analysis_snapshot_retention_days=365)),
            patch("app.services.scanner.get_market_data", return_value=market),
            patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
            patch("app.services.scanner.calculate_indicators", return_value=technicals),
            patch("app.services.scanner.explain_analysis", return_value="Mock explanation"),
            patch("app.services.scanner.build_macro_context", return_value=None),
            patch(
                "app.services.scanner.fetch_recent_filings",
                return_value=EdgarCollection(
                    ticker="AAPL",
                    cik=320193,
                    company_name="Apple Inc.",
                    filings=[],
                    fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                ),
            ),
        ):
            baseline = analyze_ticker("aapl", db=None, use_ai_explanation=True)

        with (
            patch("app.services.scanner.get_settings", return_value=SimpleNamespace(openai_api_key=None, analysis_snapshot_retention_count=50, analysis_snapshot_retention_days=365)),
            patch("app.services.scanner.get_market_data", return_value=market),
            patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
            patch("app.services.scanner.calculate_indicators", return_value=technicals),
            patch("app.services.scanner.explain_analysis", return_value="Mock explanation"),
            patch("app.services.scanner.build_macro_context", return_value=None),
            patch(
                "app.services.scanner.fetch_recent_filings",
                return_value=EdgarCollection(
                    ticker="AAPL",
                    cik=320193,
                    company_name="Apple Inc.",
                    filings=[
                        EdgarFiling(
                            form_type="8-K",
                            filing_date="2026-05-30",
                            accession_number="0000320193-26-000020",
                            description="Current report",
                            sec_url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000020/0000320193-26-000020-index.htm",
                        )
                    ],
                    fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                ),
            ),
        ):
            response = analyze_ticker("aapl", db=None, use_ai_explanation=True)

        self.assertGreater(response.scores.risk_score, baseline.scores.risk_score)
        self.assertLess(response.scores.final_score, baseline.scores.final_score)
        self.assertIsNotNone(response.sec_filings)
        self.assertTrue(any("8-K" in note for note in response.operation_notes))

    def test_analyze_ticker_adds_market_session_for_closed_market(self) -> None:
        market = {
            "ticker": "AAPL",
            "price": 189.12,
            "currency": "USD",
            "history": pd.DataFrame({"Close": [100.0, 101.0, 102.0]}),
            "info": {
                "exchangeTimezoneName": "America/New_York",
                "earningsDate": [
                    datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc),
                    datetime(2026, 6, 13, 20, 0, tzinfo=timezone.utc),
                ],
                "exDividendDate": datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
            },
            "published_at": datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
            "fetched_at": datetime(2026, 6, 1, 20, 30, tzinfo=timezone.utc),
            "event_calendar": {
                "summary": "Next earnings around 2026-06-12; Next ex-dividend around 2026-06-10",
                "upcoming_events": [
                    {
                        "name": "earnings",
                        "scheduled_at": datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc),
                        "window_start_at": datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc),
                        "window_end_at": datetime(2026, 6, 13, 20, 0, tzinfo=timezone.utc),
                        "note": "Derived from yfinance company profile earnings dates.",
                    },
                    {
                        "name": "ex_dividend",
                        "scheduled_at": datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
                        "note": "Derived from yfinance company profile dividend dates.",
                    },
                ],
            },
        }
        fundamentals = Fundamentals(company_name="Apple Inc.", sector="Technology")
        technicals = TechnicalIndicators(change_1d_pct=1.0)
        scoring = SimpleNamespace(
            scores=Scores(
                momentum_score=60.0,
                valuation_score=55.0,
                risk_score=35.0,
                final_score=62.5,
            ),
            recommendation="NEUTRAL",
            short_reason="Neutral: sample reason.",
            reasons=["price is above MA50"],
        )

        with (
            patch("app.services.scanner.get_settings", return_value=SimpleNamespace(openai_api_key=None, analysis_snapshot_retention_count=50, analysis_snapshot_retention_days=365)),
            patch("app.services.scanner.get_market_data", return_value=market),
            patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
            patch("app.services.scanner.calculate_indicators", return_value=technicals),
            patch("app.services.scanner.score_stock", return_value=scoring),
            patch("app.services.scanner.explain_analysis", return_value="Mock explanation"),
        ):
            response = analyze_ticker("aapl", db=None, use_ai_explanation=True)

        self.assertIsNotNone(response.market_session)
        self.assertEqual(response.market_session.status, "after-hours")
        self.assertEqual(response.market_session.freshness_state, "session_closed")
        self.assertTrue(any("session" in note.lower() for note in response.operation_notes))
        self.assertIsNotNone(response.event_calendar)
        self.assertTrue(
            any("earnings" in note.lower() for note in response.operation_notes)
            or any("ex-dividend" in note.lower() for note in response.operation_notes)
        )

    def test_market_data_builds_event_calendar_from_profile_fields(self) -> None:
        history = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.date_range("2026-05-25", periods=3, tz="UTC"),
        )
        settings = SimpleNamespace(
            market_data_timeout_seconds=5.0,
            market_data_max_attempts=1,
            market_data_retry_backoff_seconds=0.0,
        )

        with (
            patch("app.services.market_data.get_settings", return_value=settings),
            patch("app.services.market_data.yf.download", return_value=history),
            patch("app.services.market_data.yf.Ticker", return_value=SimpleNamespace()),
            patch(
                "app.services.market_data._safe_info",
                return_value={
                    "exchangeTimezoneName": "America/New_York",
                    "earningsDate": [
                        datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc),
                        datetime(2026, 6, 13, 20, 0, tzinfo=timezone.utc),
                    ],
                    "exDividendDate": datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
                },
            ),
            patch("app.services.market_data._safe_fast_info", return_value={"currency": "USD"}),
        ):
            data = market_data.get_market_data("aapl")

        self.assertIsNotNone(data["event_calendar"])
        self.assertIn("earnings", data["event_calendar"]["summary"].lower())
        self.assertEqual(data["event_calendar"]["upcoming_events"][0]["name"], "earnings")

    def test_analyze_ticker_persists_snapshot(self) -> None:
        market = {
            "ticker": "AAPL",
            "price": 189.12,
            "currency": "USD",
            "history": pd.DataFrame({"Close": [100.0, 101.0, 102.0]}),
            "info": {
                "quoteType": "EQUITY",
                "exchange": "NMS",
                "exchangeTimezoneName": "America/New_York",
                "currency": "USD",
                "longName": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "primaryExchange": "NASDAQ",
                "isin": "US0378331005",
                "figi": "BBG000B9XRY4",
            },
        }
        fundamentals = Fundamentals(company_name="Apple Inc.", sector="Technology")
        technicals = TechnicalIndicators(change_1d_pct=1.0)
        scoring = SimpleNamespace(
            scores=Scores(
                momentum_score=60.0,
                valuation_score=55.0,
                risk_score=35.0,
                final_score=62.5,
            ),
            recommendation="NEUTRAL",
            short_reason="Neutral: sample reason.",
            reasons=["price is above MA50"],
        )
        edgar_collection = EdgarCollection(
            ticker="AAPL",
            cik=320193,
            company_name="Apple Inc.",
            filings=[
                EdgarFiling(
                    form_type="10-Q",
                    filing_date="2026-04-30",
                    accession_number="0000320193-26-000010",
                    description="Quarterly report",
                    sec_url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-20260329.htm",
                )
            ],
            fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "snapshot.db"
            engine = create_engine(f"sqlite:///{db_path}")
            self.addCleanup(engine.dispose)
            Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

            with Session() as db:
                with (
                    patch(
                        "app.services.market_data.get_settings",
                        return_value=SimpleNamespace(
                            market_data_timeout_seconds=5.0,
                            market_data_max_attempts=3,
                            market_data_retry_backoff_seconds=0.0,
                        ),
                    ),
                    patch("app.services.market_data.yf.download", return_value=market["history"]),
                    patch("app.services.market_data.yf.Ticker", return_value=SimpleNamespace()),
                    patch("app.services.market_data._safe_info", return_value=market["info"]),
                    patch("app.services.market_data._safe_fast_info", return_value={}),
                    patch("app.services.market_data.time.sleep"),
                    patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
                    patch("app.services.scanner.calculate_indicators", return_value=technicals),
                    patch("app.services.scanner.score_stock", return_value=scoring) as score_stock_mock,
                    patch("app.services.scanner.fetch_recent_filings", return_value=edgar_collection),
                ):
                    response = analyze_ticker("aapl", db=db, use_ai_explanation=False)

                rows = db.query(AnalysisSnapshot).all()
                instruments = db.query(InstrumentRegistry).all()
                sources = db.query(SourceSnapshot).all()

        self.assertEqual(response.ticker, "AAPL")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ticker, "AAPL")
        self.assertEqual(rows[0].final_score, 62.5)
        self.assertEqual(len(instruments), 1)
        self.assertEqual(instruments[0].symbol, "AAPL")
        self.assertEqual(instruments[0].asset_type, "equity")
        self.assertEqual(instruments[0].exchange_code, "NMS")
        self.assertEqual(instruments[0].provider_aliases[0], "AAPL")
        providers = db.query(ProviderRegistry).all()
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].name, "yfinance")
        self.assertEqual(providers[0].source_tier, "Tier 2")
        self.assertIsNotNone(providers[0].last_success_at)
        self.assertEqual(len(sources), 2)
        source_by_provider = {s.provider_name: s for s in sources}
        self.assertIn("yfinance", source_by_provider)
        self.assertIn("edgar", source_by_provider)
        yfinance_source = source_by_provider["yfinance"]
        self.assertEqual(yfinance_source.ticker, "AAPL")
        self.assertEqual(yfinance_source.price_adjustment_policy, "raw_close")
        self.assertEqual(yfinance_source.payload["provider_name"], "yfinance")
        self.assertIsNotNone(yfinance_source.content_hash)
        edgar_source = source_by_provider["edgar"]
        self.assertEqual(edgar_source.ticker, "AAPL")
        self.assertEqual(edgar_source.provider_name, "edgar")
        self.assertEqual(edgar_source.source_tier, "Tier 1")
        self.assertEqual(edgar_source.payload["payload_extra"]["filings"][0]["form_type"], "10-Q")
        self.assertEqual(response.price_adjustment_policy, "raw_close")
        self.assertEqual(response.source_provenance.provider_name, "yfinance")
        self.assertFalse(response.data_quality.stale)
        self.assertIsNotNone(response.fx)
        self.assertEqual(response.fx.base_currency, "USD")
        self.assertIsNotNone(response.sec_filings)
        score_stock_mock.assert_called_once()
        self.assertEqual(
            score_stock_mock.call_args.kwargs["event_calendar"],
            market.get("event_calendar"),
        )

    def test_scan_tickers_sorts_results_and_collects_errors(self) -> None:
        analysis_high = make_analysis("MSFT", 82.0)
        analysis_low = make_analysis("AAPL", 55.0)

        with patch(
            "app.services.scanner.analyze_ticker",
            side_effect=[analysis_low, analysis_high, RuntimeError("boom")],
        ):
            response = scan_tickers(["AAPL", "MSFT", "NVDA"], db=None)

        self.assertEqual([item.ticker for item in response.results], ["MSFT", "AAPL"])
        self.assertEqual(response.results[0].final_score, 82.0)
        self.assertEqual(response.errors[0].ticker, "NVDA")
        self.assertTrue(response.summary.partial_failure)
        self.assertEqual(response.summary.requested_count, 3)
        self.assertEqual(response.summary.success_count, 2)
        self.assertEqual(response.summary.error_count, 1)
        self.assertEqual(response.summary.failed_tickers, ["NVDA"])
        self.assertIn("failures", response.summary.message)
        self.assertTrue(response.summary.notes)
        self.assertIn("Partial failure", response.summary.notes[0])

    def test_scan_tickers_skips_edgar_fetches(self) -> None:
        analysis = make_analysis("AAPL", 55.0)

        with (
            patch("app.services.scanner.analyze_ticker", return_value=analysis) as analyze_mock,
            patch("app.services.scanner.fetch_recent_filings") as filings_mock,
        ):
            response = scan_tickers(["AAPL"], db=None)

        self.assertEqual(len(response.results), 1)
        analyze_mock.assert_called_once()
        filings_mock.assert_not_called()

    def test_scan_tickers_adds_event_calendar_notes_to_summary(self) -> None:
        analysis = AnalyzeResponse(
            ticker="AAPL",
            generated_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            price=100.0,
            currency="USD",
            fundamentals=Fundamentals(company_name="Apple Inc."),
            technicals=TechnicalIndicators(),
            scores=Scores(
                momentum_score=50.0,
                valuation_score=50.0,
                risk_score=50.0,
                final_score=62.0,
            ),
            recommendation="NEUTRAL",
            short_reason="AAPL short reason",
            explanation="AAPL explanation",
            event_calendar={
                "summary": "Next earnings around 2026-06-12",
                "upcoming_events": [
                    {
                        "name": "earnings",
                        "scheduled_at": datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc),
                        "note": "Derived from yfinance company profile earnings dates.",
                    }
                ],
            },
        )

        with patch("app.services.scanner.analyze_ticker", return_value=analysis):
            response = scan_tickers(["AAPL"], db=None)

        self.assertTrue(response.summary.notes)
        self.assertTrue(any("earnings" in note.lower() for note in response.summary.notes))

    def test_openai_budget_exhaustion_uses_rule_based_explanation(self) -> None:
        payload = {
            "ticker": "AAPL",
            "price": 189.12,
            "currency": "USD",
            "fundamentals": {},
            "technicals": {},
            "scores": {"final_score": 62.5},
            "recommendation": "NEUTRAL",
            "short_reason": "Neutral: sample reason.",
        }
        settings = SimpleNamespace(
            openai_api_key="sk-test",
            openai_model="gpt-4.1-mini",
            openai_call_budget=0,
        )

        with (
            patch("app.services.ai_explainer.get_settings", return_value=settings),
            patch("app.services.ai_explainer._openai_explanation") as openai_mock,
        ):
            text = explain_analysis(payload, ["price is above MA50"])

        self.assertIn("Лимит OpenAI-вызовов исчерпан", text)
        openai_mock.assert_not_called()


class ConfigurationTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_get_settings_parses_api_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_HOST": "127.0.0.1",
                "APP_PORT": "9100",
                "ALLOW_REMOTE_API": "0",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()

        self.assertEqual(settings.api_host, "127.0.0.1")
        self.assertEqual(settings.api_port, 9100)
        self.assertFalse(settings.allow_remote_api)

    def test_get_settings_rejects_invalid_port(self) -> None:
        with patch.dict(os.environ, {"APP_PORT": "not-a-number"}, clear=False):
            get_settings.cache_clear()
            with self.assertRaises(ConfigurationError) as exc:
                get_settings()

        self.assertIn("APP_PORT must be an integer", str(exc.exception))

    def test_get_settings_parses_runtime_budgets(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MARKET_DATA_CACHE_TTL_SECONDS": "900",
                "PROVIDER_CALL_BUDGET": "321",
                "OPENAI_CALL_BUDGET": "12",
                "TELEGRAM_SEND_BUDGET": "44",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()

        self.assertEqual(settings.market_data_cache_ttl_seconds, 900)
        self.assertEqual(settings.provider_call_budget, 321)
        self.assertEqual(settings.openai_call_budget, 12)
        self.assertEqual(settings.telegram_send_budget, 44)

    def test_get_settings_parses_telegram_allowlist(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_ALLOWED_CHAT_IDS": "101, 202,101, 303",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()

        self.assertEqual(settings.telegram_allowed_chat_ids, [101, 202, 303])

    def test_get_settings_rejects_invalid_telegram_allowlist(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_ALLOWED_CHAT_IDS": "101, bad-id, 303",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            with self.assertRaises(ConfigurationError) as exc:
                get_settings()

        self.assertIn(
            "TELEGRAM_ALLOWED_CHAT_IDS must contain comma-separated integers",
            str(exc.exception),
        )

    def test_get_settings_parses_snapshot_retention_policy(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ANALYSIS_SNAPSHOT_RETENTION_COUNT": "17",
                "ANALYSIS_SNAPSHOT_RETENTION_DAYS": "90",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()

        self.assertEqual(settings.analysis_snapshot_retention_count, 17)
        self.assertEqual(settings.analysis_snapshot_retention_days, 90)

    def test_startup_diagnostics_warn_on_remote_api_without_policy(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_HOST": "0.0.0.0",
                "ALLOW_REMOTE_API": "0",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()

        diagnostics = build_startup_diagnostics(settings)

        self.assertTrue(
            any(
                "remote API exposure is disabled by policy" in warning
                for warning in diagnostics.warnings
            )
        )
        with self.assertRaises(ConfigurationError):
            enforce_local_api_policy(settings)

    def test_startup_diagnostics_warn_on_telegram_allowlist(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_ALLOWED_CHAT_IDS": "101,202",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()

        diagnostics = build_startup_diagnostics(settings)

        self.assertEqual(diagnostics.summary["telegram_allowed_chat_ids"], "2")
        self.assertTrue(
            any(
                "Telegram access control is enabled" in warning
                for warning in diagnostics.warnings
            )
        )


class ApiRouteTests(unittest.TestCase):
    def test_analyze_endpoint_serializes_response(self) -> None:
        analysis = make_analysis("AAPL", 77.7)

        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.analyze_ticker", return_value=analysis),
            TestClient(app) as client,
        ):
            response = client.get("/analyze/AAPL")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ticker"], "AAPL")
        self.assertEqual(body["scores"]["final_score"], 77.7)

    def test_analyze_endpoint_uses_market_data_status_code(self) -> None:
        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch(
                "app.api.routes.analyze_ticker",
                side_effect=market_data.MarketDataError("provider down", status_code=503),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/analyze/AAPL")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "provider down")

    def test_scan_endpoint_serializes_sorted_results(self) -> None:
        scan_response = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="MSFT",
                    price=101.0,
                    final_score=80.0,
                    momentum_score=60.0,
                    valuation_score=55.0,
                    risk_score=40.0,
                    recommendation="NEUTRAL",
                    short_reason="MSFT short reason",
                )
            ],
            errors=[],
            summary=SimpleNamespace(
                requested_count=1,
                success_count=1,
                error_count=0,
                partial_failure=False,
                message="Scan completed successfully for 1 tickers.",
                failed_tickers=[],
            ),
        )

        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.scan_tickers", return_value=scan_response),
            TestClient(app) as client,
        ):
            response = client.post("/scan", json={"tickers": ["msft"]})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["results"][0]["ticker"], "MSFT")
        self.assertEqual(body["results"][0]["final_score"], 80.0)
        self.assertEqual(body["summary"]["success_count"], 1)
        self.assertFalse(body["summary"]["partial_failure"])

    def test_recent_analyses_endpoint_serializes_rows(self) -> None:
        row = SimpleNamespace(
            id=1,
            ticker="AAPL",
            company_name="Apple Inc.",
            price=189.12,
            final_score=77.7,
            recommendation="NEUTRAL",
            created_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
        )

        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.list_recent_snapshots", return_value=[row]),
            TestClient(app) as client,
        ):
            response = client.get("/analyses/recent")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["ticker"], "AAPL")
        self.assertEqual(body[0]["price"], 189.12)

    def test_analysis_detail_endpoint_serializes_payload(self) -> None:
        row = SimpleNamespace(
            id=7,
            ticker="AAPL",
            company_name="Apple Inc.",
            price=189.12,
            final_score=77.7,
            recommendation="NEUTRAL",
            created_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            payload={
                "ticker": "AAPL",
                "generated_at": "2026-05-28T00:00:00+00:00",
                "price": 189.12,
                "currency": "USD",
            },
        )

        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.get_snapshot_by_id", return_value=row),
            TestClient(app) as client,
        ):
            response = client.get("/analyses/7")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], 7)
        self.assertEqual(body["ticker"], "AAPL")
        self.assertEqual(body["payload"]["price"], 189.12)

    def test_analysis_detail_endpoint_returns_404_for_missing_snapshot(self) -> None:
        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.get_snapshot_by_id", return_value=None),
            TestClient(app) as client,
        ):
            response = client.get("/analyses/999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Analysis snapshot 999 not found")

    def test_instrument_detail_endpoint_serializes_registry(self) -> None:
        row = SimpleNamespace(
            id=3,
            symbol="AAPL",
            provider_symbol="AAPL",
            exchange_code="NMS",
            mic="XNGS",
            country="United States",
            timezone="America/New_York",
            currency="USD",
            asset_type="equity",
            company_name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
            primary_listing="NASDAQ",
            isin="US0378331005",
            figi="BBG000B9XRY4",
            provider_aliases=["AAPL", "Apple Inc."],
            last_seen_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            created_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
        )

        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.get_instrument_by_symbol", return_value=row),
            TestClient(app) as client,
        ):
            response = client.get("/instruments/AAPL")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["symbol"], "AAPL")
        self.assertEqual(body["asset_type"], "equity")
        self.assertEqual(body["provider_aliases"], ["AAPL", "Apple Inc."])

    def test_provider_index_endpoint_serializes_registry(self) -> None:
        row = SimpleNamespace(
            id=11,
            name="yfinance",
            source_url="https://github.com/ranaroussi/yfinance",
            source_tier="Tier 2",
            data_category="market_data",
            capability_list=["historical_prices", "company_profile", "fast_info"],
            legal_terms_note="Respect upstream terms and rate limits; no login bypass.",
            cache_ttl_seconds=3600,
            retry_attempts=3,
            failure_taxonomy=["unavailable", "stale", "rate_limited"],
            last_seen_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            last_success_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            last_failure_at=None,
            last_failure_mode=None,
            created_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
        )

        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.list_providers", return_value=[row]),
            TestClient(app) as client,
        ):
            response = client.get("/providers")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["name"], "yfinance")
        self.assertEqual(body[0]["source_tier"], "Tier 2")
        self.assertEqual(body[0]["failure_taxonomy"], ["unavailable", "stale", "rate_limited"])

    def test_provider_detail_endpoint_serializes_registry(self) -> None:
        row = SimpleNamespace(
            id=11,
            name="yfinance",
            source_url="https://github.com/ranaroussi/yfinance",
            source_tier="Tier 2",
            data_category="market_data",
            capability_list=["historical_prices", "company_profile", "fast_info"],
            legal_terms_note="Respect upstream terms and rate limits; no login bypass.",
            cache_ttl_seconds=3600,
            retry_attempts=3,
            failure_taxonomy=["unavailable", "stale", "rate_limited"],
            last_seen_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            last_success_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            last_failure_at=None,
            last_failure_mode=None,
            created_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc),
        )

        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.get_provider_by_name", return_value=row),
            TestClient(app) as client,
        ):
            response = client.get("/providers/yfinance")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], "yfinance")
        self.assertEqual(body["cache_ttl_seconds"], 3600)

    def test_coverage_endpoint_serializes_matrix(self) -> None:
        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            TestClient(app) as client,
        ):
            response = client.get("/coverage")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("U.S. listed equities on major exchanges", body["supported_markets"])
        self.assertIn("No live news ingestion yet", body["known_gaps"])

    def test_ready_endpoint_reports_database_ok(self) -> None:
        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.check_database"),
            TestClient(app) as client,
        ):
            response = client.get("/ready")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["checks"]["database"], "ok")

    def test_ready_endpoint_reports_database_failure(self) -> None:
        with (
            patch("app.services.telegram_bot.TelegramBotService.start", new=AsyncMock(return_value=None)),
            patch("app.services.telegram_bot.TelegramBotService.stop", new=AsyncMock(return_value=None)),
            patch("app.api.routes.check_database", side_effect=RuntimeError("db down")),
            TestClient(app) as client,
        ):
            response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["status"], "not_ready")
