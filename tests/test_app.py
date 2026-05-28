from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, resolve_database_url
from app.api.routes import health, root
from app.main import app
from app.schemas import (
    AnalyzeResponse,
    Fundamentals,
    ScanRequest,
    Scores,
    TechnicalIndicators,
)
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
        self.assertEqual(health_response.status, "ok")
        self.assertEqual(health_response.app, "Stock AI Assistant")

    def test_scan_request_normalizes_and_deduplicates_tickers(self) -> None:
        request = ScanRequest(tickers=[" aapl ", "MSFT", "aapl", "", "  nvda "])

        self.assertEqual(request.tickers, ["AAPL", "MSFT", "NVDA"])

    def test_resolve_database_url_uses_project_root_for_relative_sqlite_paths(self) -> None:
        resolved = resolve_database_url("sqlite:///./stock_ai_assistant.db")

        self.assertTrue(resolved.startswith("sqlite:///"))
        self.assertIn(str(Path(PROJECT_ROOT / "stock_ai_assistant.db").resolve()), resolved)

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
