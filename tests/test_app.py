from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import PROJECT_ROOT, resolve_database_url
from app.api.routes import health, root
from app.database import Base
from app.models import AnalysisSnapshot
from app.main import app
from app.schemas import (
    AnalyzeResponse,
    Fundamentals,
    ScanRequest,
    Scores,
    TechnicalIndicators,
)
from app.services import market_data
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
        recommendation="HOLD",
        short_reason=f"{ticker} short reason",
        explanation=f"{ticker} explanation",
    )


class AppSmokeTests(unittest.TestCase):
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
            recommendation="HOLD",
            short_reason="HOLD: sample reason.",
            reasons=["price is above MA50"],
        )

        with (
            patch("app.services.scanner.get_market_data", return_value=market),
            patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
            patch("app.services.scanner.calculate_indicators", return_value=technicals),
            patch("app.services.scanner.score_stock", return_value=scoring),
            patch("app.services.scanner.explain_analysis", return_value="Mock explanation"),
        ):
            response = analyze_ticker("aapl", db=None, use_ai_explanation=True)

        self.assertEqual(response.ticker, "AAPL")
        self.assertEqual(response.price, 189.12)
        self.assertEqual(response.explanation, "Mock explanation")
        self.assertIsNotNone(response.generated_at.tzinfo)

    def test_analyze_ticker_persists_snapshot(self) -> None:
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
            recommendation="HOLD",
            short_reason="HOLD: sample reason.",
            reasons=["price is above MA50"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "snapshot.db"
            engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

            with Session() as db:
                with (
                    patch("app.services.scanner.get_market_data", return_value=market),
                    patch("app.services.scanner.extract_fundamentals", return_value=fundamentals),
                    patch("app.services.scanner.calculate_indicators", return_value=technicals),
                    patch("app.services.scanner.score_stock", return_value=scoring),
                ):
                    response = analyze_ticker("aapl", db=db, use_ai_explanation=False)

                rows = db.query(AnalysisSnapshot).all()

        self.assertEqual(response.ticker, "AAPL")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ticker, "AAPL")
        self.assertEqual(rows[0].final_score, 62.5)

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
                    recommendation="HOLD",
                    short_reason="MSFT short reason",
                )
            ],
            errors=[],
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

    def test_recent_analyses_endpoint_serializes_rows(self) -> None:
        row = SimpleNamespace(
            id=1,
            ticker="AAPL",
            company_name="Apple Inc.",
            price=189.12,
            final_score=77.7,
            recommendation="HOLD",
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
