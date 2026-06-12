from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.runtime_budget import reset_runtime_budgets
from app.services.telegram_bot import TelegramBotService


class TelegramWatchlistTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        reset_runtime_budgets()
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "watchlists.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.session_patcher = patch("app.services.telegram_bot.SessionLocal", self.session_factory)
        self.session_patcher.start()
        # Mock news collector to prevent GDELT / external network calls in digest tests.
        self.news_patcher = patch(
            "app.services.telegram_bot.build_news_context",
            return_value=SimpleNamespace(items=[], overall_sentiment_label="neutral", high_impact_items=[]),
        )
        self.news_patcher.start()
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
        self.news_patcher.stop()
        self.engine.dispose()
        self._tmpdir.cleanup()

    def test_resolve_action_recognizes_watchlist_commands(self) -> None:
        self.assertEqual(self.service._resolve_action("/watchlist"), ("watchlist", []))
        self.assertEqual(self.service._resolve_action("/scan mine"), ("scan_mine", []))
        self.assertEqual(self.service._resolve_action("/scan AAPL msft"), ("scan", ["AAPL", "MSFT"]))
        self.assertEqual(self.service._resolve_action("/add AAPL MSFT"), ("add", ["AAPL", "MSFT"]))
        self.assertEqual(self.service._resolve_action("/remove AAPL"), ("remove", ["AAPL"]))
        self.assertEqual(self.service._resolve_action("/confidence 0.75"), ("confidence", ["0.75"]))

    async def test_add_and_show_watchlist(self) -> None:
        send_mock = AsyncMock()

        with patch.object(self.service, "_send_message", send_mock):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/add AAPL msft AAPL",
                    }
                }
            )
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/watchlist",
                    }
                }
            )

        subscription = self.service._subscription_for_chat(101)
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.watchlist_symbols, ["AAPL", "MSFT"])
        self.assertIn("Добавил в твой список", send_mock.await_args_list[0].args[1])
        self.assertIn("Твой список тикеров", send_mock.await_args_list[1].args[1])

    async def test_scan_mine_uses_personal_watchlist(self) -> None:
        self.service._upsert_subscription(202, username="bob", active=True, watchlist_symbols=["AAPL", "NVDA"])
        send_mock = AsyncMock()
        scan_response = SimpleNamespace(results=[], errors=[], summary=SimpleNamespace())

        with (
            patch.object(self.service, "_send_message", send_mock),
            patch("app.services.telegram_bot.scan_tickers", return_value=scan_response) as scan_mock,
        ):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 202},
                        "from": {"username": "bob"},
                        "text": "/scan mine",
                    }
                }
            )

        scan_mock.assert_called_once_with(["AAPL", "NVDA"], None, "ru")
        self.assertIn("Запускаю сканирование твоего списка", send_mock.await_args_list[0].args[1])

    async def test_scan_mine_uses_saved_language(self) -> None:
        self.service._upsert_subscription(
            204,
            username="eve",
            active=True,
            watchlist_symbols=["AAPL"],
            preferences={"language": "en"},
        )
        send_mock = AsyncMock()
        scan_response = SimpleNamespace(results=[], errors=[], summary=SimpleNamespace())

        with (
            patch.object(self.service, "_send_message", send_mock),
            patch("app.services.telegram_bot.scan_tickers", return_value=scan_response) as scan_mock,
        ):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 204},
                        "from": {"username": "eve"},
                        "text": "/scan mine",
                    }
                }
            )

        scan_mock.assert_called_once_with(["AAPL"], None, "en")

    async def test_scan_with_explicit_tickers_uses_command_arguments(self) -> None:
        send_mock = AsyncMock()
        scan_response = SimpleNamespace(
            results=[
                SimpleNamespace(
                    ticker="AAPL",
                    recommendation="NEUTRAL",
                    final_score=77.1,
                    price=189.12,
                    short_reason="sample reason",
                    confidence=0.92,
                ),
                SimpleNamespace(
                    ticker="MSFT",
                    recommendation="NEUTRAL",
                    final_score=71.3,
                    price=101.25,
                    short_reason="sample reason",
                    confidence=0.41,
                ),
            ],
            errors=[],
            summary=SimpleNamespace(),
        )
        self.service._upsert_subscription(
            203,
            username="bob",
            active=True,
            preferences={"min_confidence": 0.8},
        )

        with (
            patch.object(self.service, "_send_message", send_mock),
            patch("app.services.telegram_bot.scan_tickers", return_value=scan_response) as scan_mock,
        ):
            await self.service._handle_update(
                {
                    "message": {
                        "chat": {"id": 203},
                        "from": {"username": "bob"},
                        "text": "/scan AAPL msft",
                    }
            }
        )

        scan_mock.assert_called_once_with(["AAPL", "MSFT"], None, "ru")
        self.assertIn("Запускаю сканирование: AAPL, MSFT...", send_mock.await_args_list[0].args[1])
        self.assertIn("Порог уверенности: 0.80", send_mock.await_args_list[1].args[1])
        self.assertIn("Скрыто низкоуверенных сигналов: 1", send_mock.await_args_list[1].args[1])
        self.assertIn("AAPL", send_mock.await_args_list[1].args[1])
        self.assertNotIn("MSFT:", send_mock.await_args_list[1].args[1])

    async def test_digest_uses_personal_watchlists(self) -> None:
        self.service._upsert_subscription(301, username="carol", active=True, watchlist_symbols=["AAPL"])
        self.service._upsert_subscription(302, username="dave", active=True, watchlist_symbols=["MSFT", "NVDA"])
        send_mock = AsyncMock()
        fake_scan = SimpleNamespace(
            results=[],
            errors=[],
            summary=SimpleNamespace(partial_failure=False, message="ok", failed_tickers=[]),
        )

        with (
            patch.object(self.service, "_send_message", send_mock),
            patch("app.services.telegram_bot.scan_tickers", return_value=fake_scan) as scan_mock,
        ):
            await self.service._send_digest_to_active_subscribers()

        self.assertEqual(scan_mock.call_count, 2)
        self.assertEqual(scan_mock.call_args_list[0].args[0], ["AAPL"])
        self.assertEqual(scan_mock.call_args_list[1].args[0], ["MSFT", "NVDA"])
        self.assertEqual(send_mock.await_count, 2)

    async def test_restricted_allowlist_blocks_unauthorized_chat(self) -> None:
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

        with patch.object(restricted_service, "_send_message", send_mock):
            await restricted_service._handle_update(
                {
                    "message": {
                        "chat": {"id": 101},
                        "from": {"username": "alice"},
                        "text": "/watchlist",
                    }
                }
            )

        self.assertIsNone(restricted_service._subscription_for_chat(101))
        self.assertEqual(send_mock.await_count, 1)
        self.assertIn("Доступ к этому боту ограничен", send_mock.await_args.args[1])

    async def test_digest_skips_chat_outside_allowlist(self) -> None:
        restricted_service = TelegramBotService(
            settings=SimpleNamespace(
                telegram_enabled=True,
                telegram_bot_token="123456:abcdefghijklmnopqrstuvwxyzABCDEF",
                telegram_default_tickers="AAPL,MSFT,NVDA",
                telegram_allowed_chat_ids=[401],
                telegram_digest_interval_minutes=1440,
                telegram_poll_timeout_seconds=1,
                telegram_send_budget=100,
            )
        )
        restricted_service._upsert_subscription(401, username="erin", active=True, watchlist_symbols=["AAPL"])
        restricted_service._upsert_subscription(402, username="frank", active=True, watchlist_symbols=["MSFT"])
        send_mock = AsyncMock()
        fake_scan = SimpleNamespace(
            results=[],
            errors=[],
            summary=SimpleNamespace(partial_failure=False, message="ok", failed_tickers=[]),
        )

        with (
            patch.object(restricted_service, "_send_message", send_mock),
            patch("app.services.telegram_bot.scan_tickers", return_value=fake_scan) as scan_mock,
        ):
            await restricted_service._send_digest_to_active_subscribers()

        scan_mock.assert_called_once_with(["AAPL"], None, "ru")
        self.assertEqual(send_mock.await_count, 1)
