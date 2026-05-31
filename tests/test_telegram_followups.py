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
from app.models import AnalysisSnapshot
from app.services.runtime_budget import reset_runtime_budgets
from app.services.telegram_bot import TelegramBotService


class TelegramFollowupButtonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_runtime_budgets()
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "followups.db"
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

    def tearDown(self) -> None:
        reset_runtime_budgets()
        self.session_patcher.stop()
        self.engine.dispose()
        self._tmpdir.cleanup()

    def _fake_analyze_ticker(self, ticker: str, db=None, use_ai_explanation: bool = True) -> SimpleNamespace:
        if db is not None:
            db.add(
                AnalysisSnapshot(
                    ticker=ticker.upper(),
                    company_name="Apple Inc.",
                    price=189.12,
                    final_score=63.5,
                    recommendation="NEUTRAL",
                    payload=self._analysis_payload(),
                    created_at=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
                )
            )
            db.commit()

        return SimpleNamespace(
            ticker=ticker.upper(),
            generated_at=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
            price=189.12,
            currency="USD",
            price_adjustment_policy="raw_close",
            fundamentals=SimpleNamespace(model_dump=lambda: {"company_name": "Apple Inc."}),
            technicals=SimpleNamespace(model_dump=lambda: {}),
            scores=SimpleNamespace(
                momentum_score=60.0,
                valuation_score=55.0,
                risk_score=35.0,
                final_score=63.5,
                model_dump=lambda: {
                    "momentum_score": 60.0,
                    "valuation_score": 55.0,
                    "risk_score": 35.0,
                    "final_score": 63.5,
                },
            ),
            recommendation="NEUTRAL",
            short_reason="Neutral: sample reason.",
            explanation="Sample explanation.",
            source_provenance=SimpleNamespace(
                model_dump=lambda: {
                    "provider_name": "yfinance",
                    "source_tier": "Tier 2",
                    "source_url": "https://finance.yahoo.com/",
                }
            ),
            data_quality=SimpleNamespace(
                model_dump=lambda: {"confidence": 0.81, "summary": "ok", "source_disagreed": False}
            ),
            fx=None,
            market_session=SimpleNamespace(
                model_dump=lambda: {
                    "timezone": "America/New_York",
                    "reference_time": "2026-06-01T00:00:00+00:00",
                    "status": "after-hours",
                    "is_open": False,
                    "market_open_at": "2026-06-01T13:30:00+00:00",
                    "market_close_at": "2026-06-01T20:00:00+00:00",
                    "freshness_state": "session_closed",
                    "freshness_note": "Market session is after-hours; latest bar is from 2026-05-31.",
                }
            ),
            operation_notes=[],
            model_dump=lambda mode="python": self._analysis_payload(),
        )

    def _analysis_payload(self) -> dict:
        return {
            "ticker": "AAPL",
            "generated_at": "2026-06-01T00:00:00+00:00",
            "price": 189.12,
            "currency": "USD",
            "fundamentals": {"company_name": "Apple Inc."},
            "technicals": {},
            "scores": {
                "momentum_score": 60.0,
                "valuation_score": 55.0,
                "risk_score": 35.0,
                "final_score": 63.5,
            },
            "recommendation": "NEUTRAL",
            "short_reason": "Neutral: sample reason.",
            "explanation": "Sample explanation.",
            "source_provenance": {
                "provider_name": "yfinance",
                "source_tier": "Tier 2",
                "source_url": "https://finance.yahoo.com/",
            },
            "data_quality": {"confidence": 0.81, "summary": "ok", "source_disagreed": False},
            "market_session": {
                "timezone": "America/New_York",
                "reference_time": "2026-06-01T00:00:00+00:00",
                "status": "after-hours",
                "is_open": False,
                "market_open_at": "2026-06-01T13:30:00+00:00",
                "market_close_at": "2026-06-01T20:00:00+00:00",
                "freshness_state": "session_closed",
                "freshness_note": "Market session is after-hours; latest bar is from 2026-05-31.",
            },
            "operation_notes": [],
        }

    async def test_analysis_followup_buttons_drive_callback_actions(self) -> None:
        send_mock = AsyncMock()
        answer_mock = AsyncMock()

        with (
            patch.object(self.service, "_send_message", send_mock),
            patch.object(self.service, "_answer_callback_query", answer_mock),
            patch("app.services.telegram_bot.analyze_ticker", side_effect=self._fake_analyze_ticker),
        ):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/analyze AAPL",
                    }
                }
            )

            followup_markup = send_mock.await_args_list[1].kwargs["reply_markup"]
            self.assertIn("inline_keyboard", followup_markup)
            keyboard_text = " ".join(
                button["text"]
                for row in followup_markup["inline_keyboard"]
                for button in row
            )
            self.assertIn("Источники", keyboard_text)
            self.assertIn("Пересканировать", keyboard_text)
            self.assertIn("Добавить в список", keyboard_text)

            await self.service._handle_update(
                {
                    "callback_query": {
                        "id": "cb-1",
                        "data": "watchlist_add:AAPL",
                        "message": {"chat": {"id": 101}},
                        "from": {"username": "alice"},
                    }
                }
            )

            await self.service._handle_update(
                {
                    "callback_query": {
                        "id": "cb-2",
                        "data": "sources:AAPL",
                        "message": {"chat": {"id": 101}},
                        "from": {"username": "alice"},
                    }
                }
            )

        self.assertEqual(answer_mock.await_count, 2)
        subscription = self.service._subscription_for_chat(101)
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.watchlist_symbols, ["AAPL"])
        self.assertIn("Добавил в твой список", send_mock.await_args_list[2].args[1])
        self.assertIn("provider: yfinance", send_mock.await_args_list[3].args[1].lower())
        self.assertIn("inline_keyboard", send_mock.await_args_list[3].kwargs["reply_markup"])

    async def test_callback_queries_respect_allowlist(self) -> None:
        restricted_service = TelegramBotService(
            settings=SimpleNamespace(
                telegram_enabled=True,
                telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF",
                telegram_default_tickers="AAPL,MSFT,NVDA",
                telegram_allowed_chat_ids=[999],
                telegram_digest_interval_minutes=1440,
                telegram_poll_timeout_seconds=1,
                telegram_send_budget=100,
            )
        )
        send_mock = AsyncMock()
        answer_mock = AsyncMock()

        with (
            patch.object(restricted_service, "_send_message", send_mock),
            patch.object(restricted_service, "_answer_callback_query", answer_mock),
        ):
            await restricted_service._handle_update(
                {
                    "callback_query": {
                        "id": "cb-3",
                        "data": "sources:AAPL",
                        "message": {"chat": {"id": 101}},
                        "from": {"username": "alice"},
                    }
                }
            )

        self.assertEqual(answer_mock.await_count, 1)
        self.assertEqual(send_mock.await_count, 1)
        self.assertIn("ограничен", send_mock.await_args_list[0].args[1].lower())
        self.assertIsNone(restricted_service._subscription_for_chat(101))
