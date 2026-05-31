from __future__ import annotations

from datetime import datetime, timezone
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AnalysisSnapshot, SourceSnapshot
from app.services.runtime_budget import reset_runtime_budgets
from app.services.telegram_bot import TelegramBotService


class TelegramDetailCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_runtime_budgets()
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "details.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.session_patcher = patch("app.services.telegram_bot.SessionLocal", self.session_factory)
        self.session_patcher.start()
        self.service = TelegramBotService(
            settings=SimpleNamespace(
                telegram_enabled=True,
                telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF",
                telegram_default_tickers="AAPL,MSFT,NVDA",
                telegram_allowed_chat_ids=[],
                telegram_digest_interval_minutes=1440,
                telegram_poll_timeout_seconds=1,
                telegram_send_budget=100,
            )
        )
        self._seed_ticker("AAPL")

    def tearDown(self) -> None:
        reset_runtime_budgets()
        self.session_patcher.stop()
        self.engine.dispose()
        self._tmpdir.cleanup()

    def _seed_ticker(self, ticker: str) -> None:
        with self.session_factory() as db:
            previous_payload = self._build_payload(
                final_score=54.2,
                recommendation="WATCH",
                short_reason="WATCH: earlier sample reason.",
                explanation="Earlier explanation.",
                provider_name="yfinance",
                source_tier="Tier 2",
                fetched_at="2026-05-31T18:00:00+00:00",
                market_status="open",
                freshness_state="fresh",
                freshness_note=None,
                confidence=0.81,
            )
            latest_payload = self._build_payload(
                final_score=62.5,
                recommendation="NEUTRAL",
                short_reason="Neutral: sample reason.",
                explanation="Sample explanation.",
                provider_name="yfinance",
                source_tier="Tier 2",
                fetched_at="2026-06-01T00:00:00+00:00",
                market_status="after-hours",
                freshness_state="session_closed",
                freshness_note="Market session is after-hours; latest bar is from 2026-05-31.",
                confidence=0.75,
            )
            db.add(
                AnalysisSnapshot(
                    ticker=ticker,
                    company_name="Apple Inc.",
                    price=189.12,
                    final_score=54.2,
                    recommendation="WATCH",
                    payload=previous_payload,
                    created_at=datetime(2026, 5, 31, 18, 0, tzinfo=timezone.utc),
                )
            )
            db.add(
                AnalysisSnapshot(
                    ticker=ticker,
                    company_name="Apple Inc.",
                    price=189.12,
                    final_score=62.5,
                    recommendation="NEUTRAL",
                    payload=latest_payload,
                    created_at=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
                )
            )
            db.add(
                SourceSnapshot(
                    ticker=ticker,
                    provider_name="yfinance",
                    source_url="https://finance.yahoo.com/",
                    source_tier="Tier 2",
                    data_category="market_data",
                    extraction_method="api",
                    parser_version="1",
                    observed_at=datetime(2026, 5, 31, 23, 59, tzinfo=timezone.utc),
                    published_at=datetime(2026, 5, 31, 23, 59, tzinfo=timezone.utc),
                    fetched_at=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
                    confidence=0.75,
                    content_hash="abc123",
                    price_adjustment_policy="raw_close",
                    payload={"ticker": ticker, "provider_name": "yfinance"},
                )
            )
            db.commit()

    def _build_payload(
        self,
        *,
        final_score: float,
        recommendation: str,
        short_reason: str,
        explanation: str,
        provider_name: str,
        source_tier: str,
        fetched_at: str,
        market_status: str,
        freshness_state: str,
        freshness_note: str | None,
        confidence: float,
    ) -> dict:
        return {
            "ticker": "AAPL",
            "generated_at": "2026-06-01T00:00:00+00:00",
            "price": 189.12,
            "currency": "USD",
            "fundamentals": {},
            "technicals": {},
            "scores": {
                "momentum_score": 60.0,
                "valuation_score": 55.0,
                "risk_score": 35.0,
                "final_score": final_score,
            },
            "recommendation": recommendation,
            "short_reason": short_reason,
            "explanation": explanation,
            "source_provenance": {
                "provider_name": provider_name,
                "source_tier": source_tier,
                "source_url": "https://finance.yahoo.com/",
                "fetched_at": fetched_at,
            },
            "data_quality": {"confidence": confidence, "summary": "ok"},
            "market_session": {
                "timezone": "America/New_York",
                "reference_time": "2026-06-01T00:00:00+00:00",
                "status": market_status,
                "is_open": market_status == "open",
                "market_open_at": "2026-06-01T13:30:00+00:00",
                "market_close_at": "2026-06-01T20:00:00+00:00",
                "freshness_state": freshness_state,
                "freshness_note": freshness_note,
            },
            "operation_notes": [],
        }

    async def test_detail_commands_use_saved_snapshots(self) -> None:
        send_mock = AsyncMock()

        with patch.object(self.service, "_send_message", send_mock):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/why AAPL",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/sources AAPL",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/freshness AAPL",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/risk AAPL",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/events AAPL",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/audit AAPL",
                    }
                }
            )

        self.assertEqual(send_mock.await_count, 6)
        self.assertIn("почему это выглядит так", send_mock.await_args_list[0].args[1])
        self.assertIn("provider: yfinance", send_mock.await_args_list[1].args[1])
        self.assertIn("freshness", send_mock.await_args_list[2].args[1].lower())
        self.assertIn("risk context", send_mock.await_args_list[3].args[1].lower())
        self.assertIn("event and session context", send_mock.await_args_list[4].args[1])
        self.assertIn("Score delta vs previous", send_mock.await_args_list[5].args[1])

    async def test_calendar_today_uses_baseline_session(self) -> None:
        send_mock = AsyncMock()

        with patch.object(self.service, "_send_message", send_mock):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 102},
                        "from": {"username": "bob"},
                        "text": "/calendar today",
                    }
                }
            )

        self.assertEqual(send_mock.await_count, 1)
        self.assertIn("U.S. equity session baseline", send_mock.await_args.args[1])
